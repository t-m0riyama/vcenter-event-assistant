"""指定期間のイベント・メトリクスを集約し、ダイジェスト用コンテキストを構築する。"""

from __future__ import annotations

import uuid
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

_TOP_NOTABLE_EVENTS_LIMIT = 10
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


class DigestContext(BaseModel):
    """``[from_utc, to_utc)`` における集約（UTC 前提）。"""

    from_utc: datetime
    to_utc: datetime
    vcenter_count: int
    total_events: int = Field(description="期間内のイベント総数")
    notable_events_count: int = Field(description="notable_score >= 40 の件数")
    top_notable_events: list[DigestContextEventSnippet]
    top_event_types: list[DigestEventTypeBucket]
    high_cpu_hosts: list[HighCpuHostRow]
    high_mem_hosts: list[HighMemHostRow]


async def build_digest_context(
    session: AsyncSession,
    from_utc: datetime,
    to_utc: datetime,
    *,
    top_notable_min_score: int = 1,
) -> DigestContext:
    """``from_utc <= t < to_utc`` のイベント・サンプルを集約する（時刻は timezone-aware を想定）。"""
    if from_utc >= to_utc:
        raise ValueError("from_utc must be before to_utc")

    vc_count = await session.execute(select(func.count()).select_from(VCenter))
    ev_q = await session.execute(
        select(func.count())
        .select_from(EventRecord)
        .where(EventRecord.occurred_at >= from_utc, EventRecord.occurred_at < to_utc)
    )
    notable_q = await session.execute(
        select(func.count())
        .select_from(EventRecord)
        .where(
            EventRecord.occurred_at >= from_utc,
            EventRecord.occurred_at < to_utc,
            EventRecord.notable_score >= _NOTABLE_SCORE_THRESHOLD,
        )
    )

    top_q = await session.execute(
        select(EventRecord)
        .where(
            EventRecord.occurred_at >= from_utc,
            EventRecord.occurred_at < to_utc,
            EventRecord.notable_score >= top_notable_min_score,
        )
        .order_by(EventRecord.notable_score.desc(), EventRecord.occurred_at.desc())
        .limit(_TOP_NOTABLE_EVENTS_LIMIT)
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

    event_cnt = func.count().label("event_cnt")
    type_q = await session.execute(
        select(EventRecord.event_type, event_cnt)
        .where(EventRecord.occurred_at >= from_utc, EventRecord.occurred_at < to_utc)
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
                EventRecord.occurred_at >= from_utc,
                EventRecord.occurred_at < to_utc,
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
        .where(
            MetricSample.metric_key == "host.cpu.usage_pct",
            MetricSample.sampled_at >= from_utc,
            MetricSample.sampled_at < to_utc,
        )
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
        .where(
            MetricSample.metric_key == "host.mem.usage_pct",
            MetricSample.sampled_at >= from_utc,
            MetricSample.sampled_at < to_utc,
        )
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
        vcenter_count=int(vc_count.scalar_one() or 0),
        total_events=int(ev_q.scalar_one() or 0),
        notable_events_count=int(notable_q.scalar_one() or 0),
        top_notable_events=top_snippets,
        top_event_types=top_event_types,
        high_cpu_hosts=high_cpu,
        high_mem_hosts=high_mem,
    )
