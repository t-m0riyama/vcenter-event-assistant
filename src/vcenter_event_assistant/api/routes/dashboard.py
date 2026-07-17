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
from vcenter_event_assistant.api.schemas.dashboard import DashboardAttention
from vcenter_event_assistant.db.models import AlertRule, AlertState, EventRecord, VCenter
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


@router.get("/attention", response_model=DashboardAttention)
async def dashboard_attention(
    session: AsyncSession = Depends(get_session),
) -> DashboardAttention:
    """タブのアテンションドット用の軽量カウント。summary と違い一覧やガイドは返さない。"""
    day_ago = datetime.now(timezone.utc) - timedelta(hours=24)
    notable = await session.execute(
        select(func.count())
        .select_from(EventRecord)
        .where(EventRecord.occurred_at >= day_ago, EventRecord.notable_score >= 40)
    )
    firing = await session.execute(
        select(func.count())
        .select_from(AlertState)
        .join(AlertRule, AlertRule.id == AlertState.rule_id)
        .where(AlertState.state == "firing", AlertRule.is_enabled.is_(True))
    )
    return DashboardAttention(
        notable_events_last_24h=int(notable.scalar_one() or 0),
        firing_alerts=int(firing.scalar_one() or 0),
    )


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

    # 直近24h の時間別件数（概要カードのスパークライン用）。index 0 が最古、23 が直近 1 時間。
    # DB 方言依存の日時関数を避け、occurred_at を取得して Python 側でバケット集計する。
    hourly_q = await session.execute(
        select(EventRecord.occurred_at, EventRecord.notable_score).where(
            EventRecord.occurred_at >= day_ago
        )
    )
    events_hourly = [0] * 24
    notable_hourly = [0] * 24
    for occurred_at, score in hourly_q.all():
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        idx = min(23, max(0, int((occurred_at - day_ago).total_seconds() // 3600)))
        events_hourly[idx] += 1
        if (score or 0) >= 40:
            notable_hourly[idx] += 1

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
        events_last_24h_hourly=events_hourly,
        notable_events_last_24h_hourly=notable_hourly,
        top_notable_events=top_notable_events,
        high_cpu_hosts=high_cpu,
        high_mem_hosts=high_mem,
        top_event_types_24h=top_event_types,
    )
