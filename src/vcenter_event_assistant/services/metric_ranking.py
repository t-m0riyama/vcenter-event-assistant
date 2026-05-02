"""Metric ranking queries and row converters (shared by dashboard and digest)."""

from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import MetricSample
from vcenter_event_assistant.api.schemas import HighCpuHostRow, HighMemHostRow


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
