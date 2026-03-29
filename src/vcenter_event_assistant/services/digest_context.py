"""指定期間のイベント・メトリクスを集約し、ダイジェスト用コンテキストを構築する。"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.schemas import HighCpuHostRow, HighMemHostRow
from vcenter_event_assistant.db.models import EventRecord, MetricSample, VCenter
from vcenter_event_assistant.rules.notable import final_notable_score
from vcenter_event_assistant.services.event_scores import load_event_score_delta_map

# ダッシュボードの「要注意イベント数」と同じ閾値（notable_score >= 40）
_NOTABLE_SCORE_THRESHOLD = 40

# 要注意: DB から読む行の上限（集約前）。同一種別が多い週次でも種別単位に畳めるよう多めに取る。
_TOP_NOTABLE_RAW_FETCH_LIMIT = 200
# 要注意: 種別集約後にテンプレ・LLM に載せるグループ数の上限
_TOP_NOTABLE_EVENT_GROUPS_LIMIT = 10
_TOP_EVENT_TYPES_LIMIT = 10
_TOP_HOST_METRICS_LIMIT = 10


class DigestContextEventSnippet(BaseModel):
    """ダイジェスト用に切り詰めたイベント 1 件。"""

    id: int
    vcenter_id: uuid.UUID
    occurred_at: datetime
    event_type: str
    message: str
    severity: str | None
    entity_name: str | None
    notable_score: int


class DigestEventTypeBucket(BaseModel):
    """期間内のイベント種別ごとの件数と、代表スコア（dashboard と同様の max 算出）。"""

    event_type: str
    event_count: int
    max_notable_score: int


class DigestNotableEventGroup(BaseModel):
    """要注意イベントを event_type 単位に集約した 1 エントリ。"""

    event_type: str
    occurrence_count: int
    notable_score: int
    occurred_at_first: datetime
    occurred_at_last: datetime
    entity_name: str | None
    message: str


def group_notable_rows_by_event_type(
    snippets: list[DigestContextEventSnippet],
) -> list[DigestNotableEventGroup]:
    """
    ``DigestContextEventSnippet`` を ``event_type`` ごとにまとめ、ソート済みリストを返す。

    代表メッセージは ``occurred_at`` が最も新しい行のもの（同時刻は ``id`` 降順で安定化）。
    ``entity_name`` はグループ内で全行同一のときだけ設定し、異なれば ``None``。
    """
    if not snippets:
        return []

    buckets: dict[str, list[DigestContextEventSnippet]] = defaultdict(list)
    for s in snippets:
        buckets[s.event_type].append(s)

    groups: list[DigestNotableEventGroup] = []
    for event_type, items in buckets.items():
        occurrence_count = len(items)
        notable_score = max(x.notable_score for x in items)
        occurred_at_first = min(x.occurred_at for x in items)
        occurred_at_last = max(x.occurred_at for x in items)
        latest = [x for x in items if x.occurred_at == occurred_at_last]
        representative = max(latest, key=lambda x: x.id)
        entities = {x.entity_name for x in items}
        entity_name: str | None
        if len(entities) == 1:
            entity_name = next(iter(entities))
        else:
            entity_name = None
        groups.append(
            DigestNotableEventGroup(
                event_type=event_type,
                occurrence_count=occurrence_count,
                notable_score=notable_score,
                occurred_at_first=occurred_at_first,
                occurred_at_last=occurred_at_last,
                entity_name=entity_name,
                message=representative.message,
            )
        )

    groups.sort(
        key=lambda g: (-g.notable_score, -g.occurred_at_last.timestamp(), g.event_type),
    )
    return groups


class DigestContext(BaseModel):
    """``[from_utc, to_utc)`` における集約（UTC 前提）。"""

    from_utc: datetime
    to_utc: datetime
    vcenter_count: int
    total_events: int = Field(description="期間内のイベント総数")
    notable_events_count: int = Field(description="notable_score >= 40 の件数")
    top_notable_event_groups: list[DigestNotableEventGroup]
    top_event_types: list[DigestEventTypeBucket]
    high_cpu_hosts: list[HighCpuHostRow]
    high_mem_hosts: list[HighMemHostRow]


async def build_digest_context(
    session: AsyncSession,
    from_utc: datetime,
    to_utc: datetime,
    *,
    top_notable_min_score: int = 1,
    vcenter_id: uuid.UUID | None = None,
) -> DigestContext:
    """``from_utc <= t < to_utc`` のイベント・サンプルを集約する（時刻は timezone-aware を想定）。

    ``vcenter_id`` を指定した場合は、その vCenter に属するイベント・メトリクスのみを対象とする。
    このとき ``vcenter_count`` は単一スコープであることを示す **1** とする（登録 vCenter 総数ではない）。
    """
    if from_utc >= to_utc:
        raise ValueError("from_utc must be before to_utc")

    if vcenter_id is not None:
        vcenter_count = 1
    else:
        vc_count = await session.execute(select(func.count()).select_from(VCenter))
        vcenter_count = int(vc_count.scalar_one() or 0)

    ev_clauses = [
        EventRecord.occurred_at >= from_utc,
        EventRecord.occurred_at < to_utc,
    ]
    if vcenter_id is not None:
        ev_clauses.append(EventRecord.vcenter_id == vcenter_id)

    ev_q = await session.execute(select(func.count()).select_from(EventRecord).where(*ev_clauses))
    notable_clauses = [
        *ev_clauses,
        EventRecord.notable_score >= _NOTABLE_SCORE_THRESHOLD,
    ]
    notable_q = await session.execute(
        select(func.count()).select_from(EventRecord).where(*notable_clauses)
    )

    top_clauses = [
        *ev_clauses,
        EventRecord.notable_score >= top_notable_min_score,
    ]
    top_q = await session.execute(
        select(EventRecord)
        .where(*top_clauses)
        .order_by(EventRecord.notable_score.desc(), EventRecord.occurred_at.desc())
        .limit(_TOP_NOTABLE_RAW_FETCH_LIMIT)
    )
    top_rows = list(top_q.scalars().all())
    top_snippets = [
        DigestContextEventSnippet(
            id=r.id,
            vcenter_id=r.vcenter_id,
            occurred_at=r.occurred_at,
            event_type=r.event_type,
            message=r.message or "",
            severity=r.severity,
            entity_name=r.entity_name,
            notable_score=r.notable_score,
        )
        for r in top_rows
    ]
    grouped = group_notable_rows_by_event_type(top_snippets)
    top_groups = grouped[:_TOP_NOTABLE_EVENT_GROUPS_LIMIT]

    event_cnt = func.count().label("event_cnt")
    type_q = await session.execute(
        select(EventRecord.event_type, event_cnt)
        .where(*ev_clauses)
        .group_by(EventRecord.event_type)
        .order_by(event_cnt.desc())
        .limit(_TOP_EVENT_TYPES_LIMIT)
    )
    type_rows = [(str(et), int(c or 0)) for et, c in type_q.all()]
    top_types = [t for t, _ in type_rows]

    delta_map = await load_event_score_delta_map(session)
    max_by_type: dict[str, int] = {t: 0 for t in top_types}
    if top_types:
        ev_for_types = await session.execute(
            select(EventRecord.event_type, EventRecord.severity, EventRecord.message).where(
                *ev_clauses,
                EventRecord.event_type.in_(top_types),
            )
        )
        for et, sev, msg in ev_for_types.all():
            et_s = str(et)
            d = delta_map.get(et_s, 0)
            sc = final_notable_score(
                event_type=et_s,
                severity=sev,
                message=msg or "",
                score_delta=d,
            )
            if sc > max_by_type[et_s]:
                max_by_type[et_s] = sc

    top_event_types = [
        DigestEventTypeBucket(
            event_type=et,
            event_count=cnt,
            max_notable_score=max_by_type[et],
        )
        for et, cnt in type_rows
    ]

    metric_clauses = [
        MetricSample.metric_key == "host.cpu.usage_pct",
        MetricSample.sampled_at >= from_utc,
        MetricSample.sampled_at < to_utc,
    ]
    if vcenter_id is not None:
        metric_clauses.append(MetricSample.vcenter_id == vcenter_id)

    cpu_rank = (
        select(
            MetricSample.id,
            func.row_number()
            .over(
                partition_by=(MetricSample.vcenter_id, MetricSample.entity_moid),
                order_by=(MetricSample.value.desc(), MetricSample.sampled_at.desc()),
            )
            .label("rn"),
        )
        .where(*metric_clauses)
    ).subquery()

    cpu_q = await session.execute(
        select(MetricSample)
        .join(cpu_rank, MetricSample.id == cpu_rank.c.id)
        .where(cpu_rank.c.rn == 1)
        .order_by(MetricSample.value.desc())
        .limit(_TOP_HOST_METRICS_LIMIT)
    )
    cpu_rows = list(cpu_q.scalars().all())
    high_cpu = [
        HighCpuHostRow(
            vcenter_id=str(r.vcenter_id),
            entity_name=r.entity_name,
            entity_moid=r.entity_moid,
            value=r.value,
            sampled_at=r.sampled_at,
        )
        for r in cpu_rows
    ]

    mem_metric_clauses = [
        MetricSample.metric_key == "host.mem.usage_pct",
        MetricSample.sampled_at >= from_utc,
        MetricSample.sampled_at < to_utc,
    ]
    if vcenter_id is not None:
        mem_metric_clauses.append(MetricSample.vcenter_id == vcenter_id)

    mem_rank = (
        select(
            MetricSample.id,
            func.row_number()
            .over(
                partition_by=(MetricSample.vcenter_id, MetricSample.entity_moid),
                order_by=(MetricSample.value.desc(), MetricSample.sampled_at.desc()),
            )
            .label("rn"),
        )
        .where(*mem_metric_clauses)
    ).subquery()

    mem_q = await session.execute(
        select(MetricSample)
        .join(mem_rank, MetricSample.id == mem_rank.c.id)
        .where(mem_rank.c.rn == 1)
        .order_by(MetricSample.value.desc())
        .limit(_TOP_HOST_METRICS_LIMIT)
    )
    mem_rows = list(mem_q.scalars().all())
    high_mem = [
        HighMemHostRow(
            vcenter_id=str(r.vcenter_id),
            entity_name=r.entity_name,
            entity_moid=r.entity_moid,
            value=r.value,
            sampled_at=r.sampled_at,
        )
        for r in mem_rows
    ]

    return DigestContext(
        from_utc=from_utc,
        to_utc=to_utc,
        vcenter_count=vcenter_count,
        total_events=int(ev_q.scalar_one() or 0),
        notable_events_count=int(notable_q.scalar_one() or 0),
        top_notable_event_groups=top_groups,
        top_event_types=top_event_types,
        high_cpu_hosts=high_cpu,
        high_mem_hosts=high_mem,
    )
