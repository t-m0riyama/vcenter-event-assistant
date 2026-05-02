"""Aggregated dashboard data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas import (
    DashboardSummary,
    EventTypeCountRow,
    HighCpuHostRow,
    HighMemHostRow,
)
from vcenter_event_assistant.db.models import EventRecord, VCenter
from vcenter_event_assistant.services.vcenter_labels import load_vcenter_labels_map
from vcenter_event_assistant.services.event_type_guide_attach import (
    attach_type_guides_to_event_reads,
    attach_type_guides_to_event_type_count_rows,
)
from vcenter_event_assistant.services.metric_ranking import (
    metric_samples_to_high_host_rows,
    query_top_event_type_buckets,
    query_top_metric_hosts,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_TOP_EVENT_TYPES_LIMIT = 10


@router.get("/summary", response_model=DashboardSummary)
async def dashboard_summary(
    session: AsyncSession = Depends(get_session),
    top_notable_min_score: Annotated[
        int,
        Query(
            ge=0,
            le=100,
            description=(
                "概要の要注意イベント（上位）一覧に含める notable_score の下限（0〜100）。"
                "0 は下限なし（スコア 0 も含む）。"
            ),
        ),
    ] = 1,
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

    # 直近24h の要注意イベント上位。notable_score がクエリ下限未満の行は除外する。
    top_q = await session.execute(
        select(EventRecord)
        .where(
            EventRecord.occurred_at >= day_ago,
            EventRecord.notable_score >= top_notable_min_score,
        )
        .order_by(EventRecord.notable_score.desc(), EventRecord.occurred_at.desc())
        .limit(10)
    )
    top = list(top_q.scalars().all())

    bucket_results = await query_top_event_type_buckets(
        session,
        [EventRecord.occurred_at >= day_ago],
        limit=_TOP_EVENT_TYPES_LIMIT,
    )
    top_event_types = [
        EventTypeCountRow(
            event_type=b.event_type,
            event_count=b.event_count,
            max_notable_score=b.max_notable_score,
        )
        for b in bucket_results
    ]
    top_event_types = await attach_type_guides_to_event_type_count_rows(session, top_event_types)

    cpu_rows = await query_top_metric_hosts(session, "host.cpu.usage_pct", day_ago)
    mem_rows = await query_top_metric_hosts(session, "host.mem.usage_pct", day_ago)

    ids_for_label = {r.vcenter_id for r in cpu_rows} | {r.vcenter_id for r in mem_rows}
    label_map = await load_vcenter_labels_map(session, ids_for_label)

    high_cpu = metric_samples_to_high_host_rows(cpu_rows, label_map, row_class=HighCpuHostRow)
    high_mem = metric_samples_to_high_host_rows(mem_rows, label_map, row_class=HighMemHostRow)

    top_notable_events = await attach_type_guides_to_event_reads(session, top)

    return DashboardSummary(
        vcenter_count=int(vc_count.scalar_one() or 0),
        events_last_24h=int(ev_24.scalar_one() or 0),
        notable_events_last_24h=int(notable_24.scalar_one() or 0),
        top_notable_events=top_notable_events,
        high_cpu_hosts=high_cpu,
        high_mem_hosts=high_mem,
        top_event_types_24h=top_event_types,
    )
