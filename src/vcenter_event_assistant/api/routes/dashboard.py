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
    HighMemHostRow,
)
from vcenter_event_assistant.db.models import EventRecord, MetricSample, VCenter
from vcenter_event_assistant.rules.notable import final_notable_score
from vcenter_event_assistant.services.event_scores import load_event_score_delta_map

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
    type_rows = [(str(et), int(c or 0)) for et, c in type_q.all()]
    top_types = [t for t, _ in type_rows]

    delta_map = await load_event_score_delta_map(session)
    max_by_type: dict[str, int] = {t: 0 for t in top_types}
    if top_types:
        ev_for_types = await session.execute(
            select(EventRecord.event_type, EventRecord.severity, EventRecord.message).where(
                EventRecord.occurred_at >= day_ago,
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
        EventTypeCountRow(
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
            MetricSample.sampled_at >= day_ago,
        )
    ).subquery()

    mem_q = await session.execute(
        select(MetricSample)
        .join(mem_rank, MetricSample.id == mem_rank.c.id)
        .where(mem_rank.c.rn == 1)
        .order_by(MetricSample.value.desc())
        .limit(10)
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

    return DashboardSummary(
        vcenter_count=int(vc_count.scalar_one() or 0),
        events_last_24h=int(ev_24.scalar_one() or 0),
        notable_events_last_24h=int(notable_24.scalar_one() or 0),
        top_notable_events=[EventRead.model_validate(e) for e in top],
        high_cpu_hosts=high_cpu,
        high_mem_hosts=high_mem,
        top_event_types_24h=top_event_types,
    )
