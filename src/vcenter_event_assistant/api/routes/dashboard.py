"""Aggregated dashboard data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas import (
    DashboardSummary,
    EventRead,
    EventTypeCountRow,
    HighCpuHostRow,
)
from vcenter_event_assistant.db.models import EventRecord, MetricSample, VCenter

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_TOP_EVENT_TYPES_LIMIT = 10


@router.get("/summary", response_model=DashboardSummary)
async def dashboard_summary(
    session: AsyncSession = Depends(get_session),
) -> DashboardSummary:
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)

    vc_count = await session.execute(select(func.count()).select_from(VCenter))
    ev_24 = await session.execute(
        select(func.count()).select_from(EventRecord).where(EventRecord.occurred_at >= day_ago)
    )
    notable_24 = await session.execute(
        select(func.count())
        .select_from(EventRecord)
        .where(EventRecord.occurred_at >= day_ago, EventRecord.notable_score >= 40)
    )

    top_q = await session.execute(
        select(EventRecord)
        .where(EventRecord.occurred_at >= day_ago)
        .order_by(EventRecord.notable_score.desc(), EventRecord.occurred_at.desc())
        .limit(10)
    )
    top = list(top_q.scalars().all())

    event_cnt = func.count().label("event_cnt")
    type_q = await session.execute(
        select(EventRecord.event_type, event_cnt)
        .where(EventRecord.occurred_at >= day_ago)
        .group_by(EventRecord.event_type)
        .order_by(event_cnt.desc())
        .limit(_TOP_EVENT_TYPES_LIMIT)
    )
    top_event_types = [
        EventTypeCountRow(event_type=str(et), event_count=int(c or 0))
        for et, c in type_q.all()
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
            MetricSample.sampled_at >= day_ago,
        )
    ).subquery()

    cpu_q = await session.execute(
        select(MetricSample)
        .join(cpu_rank, MetricSample.id == cpu_rank.c.id)
        .where(cpu_rank.c.rn == 1)
        .order_by(MetricSample.value.desc())
        .limit(10)
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

    return DashboardSummary(
        vcenter_count=int(vc_count.scalar_one() or 0),
        events_last_24h=int(ev_24.scalar_one() or 0),
        notable_events_last_24h=int(notable_24.scalar_one() or 0),
        top_notable_events=[EventRead.model_validate(e) for e in top],
        high_cpu_hosts=high_cpu,
        top_event_types_24h=top_event_types,
    )
