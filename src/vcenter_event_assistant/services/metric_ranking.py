"""Metric ranking queries, event-type aggregation, and row converters (shared by dashboard and digest)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.schemas import HighCpuHostRow, HighMemHostRow
from vcenter_event_assistant.db.models import EventRecord, MetricSample
from vcenter_event_assistant.rules.notable import final_notable_score
from vcenter_event_assistant.services.event_scores import load_event_score_delta_map


async def query_top_metric_hosts(
    session: AsyncSession,
    metric_key: str,
    from_utc: datetime,
    to_utc: datetime | None = None,
    *,
    vcenter_id: uuid.UUID | None = None,
    limit: int = 10,
) -> list[MetricSample]:
    """
    Find top N hosts by peak metric value in the given window.
    Uses row_number() over (partition by vcenter_id, entity_moid order by value desc, sampled_at desc).
    """
    clauses = [
        MetricSample.metric_key == metric_key,
        MetricSample.sampled_at >= from_utc,
    ]
    if to_utc is not None:
        clauses.append(MetricSample.sampled_at < to_utc)
    if vcenter_id is not None:
        clauses.append(MetricSample.vcenter_id == vcenter_id)

    rank_subq = (
        select(
            MetricSample.id,
            func.row_number()
            .over(
                partition_by=(MetricSample.vcenter_id, MetricSample.entity_moid),
                order_by=(MetricSample.value.desc(), MetricSample.sampled_at.desc()),
            )
            .label("rn"),
        )
        .where(*clauses)
    ).subquery()

    q = (
        select(MetricSample)
        .join(rank_subq, MetricSample.id == rank_subq.c.id)
        .where(rank_subq.c.rn == 1)
        .order_by(MetricSample.value.desc())
        .limit(limit)
    )
    res = await session.execute(q)
    return list(res.scalars().all())


def metric_samples_to_high_host_rows(
    rows: list[MetricSample],
    label_map: dict[uuid.UUID, str],
    *,
    row_class: type[HighCpuHostRow] | type[HighMemHostRow],
) -> list[HighCpuHostRow] | list[HighMemHostRow]:
    """Convert MetricSample rows to HighCpuHostRow or HighMemHostRow."""
    return [
        row_class(
            vcenter_id=str(r.vcenter_id),
            vcenter_label=label_map.get(r.vcenter_id, f"{str(r.vcenter_id)[:8]}…"),
            entity_name=r.entity_name,
            entity_moid=r.entity_moid,
            value=r.value,
            sampled_at=r.sampled_at,
        )
        for r in rows
    ]


@dataclass
class EventTypeBucketResult:
    """イベント種別ごとの件数と max notable score（dashboard / digest 共通）。"""

    event_type: str
    event_count: int
    max_notable_score: int


async def query_top_event_type_buckets(
    session: AsyncSession,
    event_clauses: list,
    *,
    limit: int = 10,
) -> list[EventTypeBucketResult]:
    """期間内のイベント種別 Top N と各種別の max notable_score を返す。

    ``event_clauses`` は ``EventRecord`` に対する WHERE 条件のリスト。
    """
    event_cnt = func.count().label("event_cnt")
    type_q = await session.execute(
        select(EventRecord.event_type, event_cnt)
        .where(*event_clauses)
        .group_by(EventRecord.event_type)
        .order_by(event_cnt.desc())
        .limit(limit)
    )
    type_rows = [(str(et), int(c or 0)) for et, c in type_q.all()]
    top_types = [t for t, _ in type_rows]

    delta_map = await load_event_score_delta_map(session)
    max_by_type: dict[str, int] = {t: 0 for t in top_types}
    if top_types:
        ev_for_types = await session.execute(
            select(
                EventRecord.event_type,
                EventRecord.severity,
                EventRecord.message,
            ).where(
                *event_clauses,
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

    return [
        EventTypeBucketResult(
            event_type=et,
            event_count=cnt,
            max_notable_score=max_by_type[et],
        )
        for et, cnt in type_rows
    ]
