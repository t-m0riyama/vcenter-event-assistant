"""Aggregated dashboard data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas import DashboardSummary, EventRead
from vcenter_event_assistant.auth.dependencies import require_auth
from vcenter_event_assistant.db.models import EventRecord, MetricSample, VCenter

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def dashboard_summary(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth),
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

    cpu_q = await session.execute(
        select(MetricSample)
        .where(MetricSample.metric_key == "host.cpu.usage_pct", MetricSample.sampled_at >= day_ago)
        .order_by(MetricSample.value.desc())
        .limit(10)
    )
    cpu_rows = list(cpu_q.scalars().all())
    high_cpu = [
        {
            "vcenter_id": str(r.vcenter_id),
            "entity_name": r.entity_name,
            "entity_moid": r.entity_moid,
            "value": r.value,
            "sampled_at": r.sampled_at.isoformat(),
        }
        for r in cpu_rows
    ]

    return DashboardSummary(
        vcenter_count=int(vc_count.scalar_one() or 0),
        events_last_24h=int(ev_24.scalar_one() or 0),
        notable_events_last_24h=int(notable_24.scalar_one() or 0),
        top_notable_events=[EventRead.model_validate(e) for e in top],
        high_cpu_hosts=high_cpu,
    )
