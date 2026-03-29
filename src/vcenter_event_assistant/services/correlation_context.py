"""高 CPU メトリクス時刻をアンカーにしたイベント近接集計（チャット専用・オンデマンド）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import EventRecord, MetricSample

METRIC_KEY_CPU_PCT = "host.cpu.usage_pct"
# アンカー 1 件あたりに載せるイベント種別の最大行数（トークン抑制）
_MAX_EVENT_TYPES_PER_ANCHOR = 30


class CorrelationEventInWindow(BaseModel):
    """時間窓内のイベント種別ごとの件数と代表時刻。"""

    event_type: str
    count: int
    sample_occurred_at: datetime


class CorrelationAnchorRow(BaseModel):
    """1 件の CPU アンカーと、その前後窓内のイベント集計。"""

    host: str
    anchor_time: datetime
    cpu_at_anchor: float
    events_in_window: list[CorrelationEventInWindow]


class CpuEventCorrelationPayload(BaseModel):
    """LLM に渡す CPU–イベント近接ブロック（`digest_context` と別キーでマージする）。"""

    correlation_profile: Literal["cpu_threshold_window"] = "cpu_threshold_window"
    cpu_threshold_pct: float = Field(description="アンカー選定に用いた CPU 利用率の下限（%）")
    window_minutes: int = Field(description="アンカー時刻前後の窓の半分（± 分）。窓内のイベントを集計する")
    rows: list[CorrelationAnchorRow]


async def build_cpu_event_correlation(
    session: AsyncSession,
    from_utc: datetime,
    to_utc: datetime,
    *,
    vcenter_id: uuid.UUID | None,
    threshold_pct: float,
    window_minutes: int,
    max_anchors: int,
) -> CpuEventCorrelationPayload:
    """
    高 CPU サンプルをアンカーに、同一ホスト名のイベントを時間窓で集計する。

    - メトリクスは ``host.cpu.usage_pct``、値が閾値以上かつ期間内のサンプルを対象とする。
    - アンカーは ``entity_moid`` ごとに 1 件（値は高い順）に絞り、最大 ``max_anchors`` 件。
    - イベントは ``entity_name`` がメトリクス行の ``entity_name`` と一致するもののみ（MVP）。
    """
    if from_utc >= to_utc:
        raise ValueError("from_utc must be before to_utc")
    if window_minutes < 1:
        raise ValueError("window_minutes must be >= 1")

    metric_clauses = [
        MetricSample.metric_key == METRIC_KEY_CPU_PCT,
        MetricSample.value >= threshold_pct,
        MetricSample.sampled_at >= from_utc,
        MetricSample.sampled_at < to_utc,
    ]
    if vcenter_id is not None:
        metric_clauses.append(MetricSample.vcenter_id == vcenter_id)

    m_stmt = (
        select(MetricSample)
        .where(and_(*metric_clauses))
        .order_by(MetricSample.value.desc(), MetricSample.sampled_at.desc())
    )
    m_rows = list((await session.execute(m_stmt)).scalars().all())

    seen_moids: set[str] = set()
    anchors: list[MetricSample] = []
    for s in m_rows:
        if s.entity_moid in seen_moids:
            continue
        seen_moids.add(s.entity_moid)
        anchors.append(s)
        if len(anchors) >= max_anchors:
            break

    delta = timedelta(minutes=window_minutes)
    out_rows: list[CorrelationAnchorRow] = []

    for m in anchors:
        host = (m.entity_name or "").strip()
        if not host:
            continue

        win_start = m.sampled_at - delta
        win_end = m.sampled_at + delta

        ev_clauses = [
            EventRecord.vcenter_id == m.vcenter_id,
            EventRecord.entity_name == host,
            EventRecord.occurred_at >= win_start,
            EventRecord.occurred_at <= win_end,
        ]
        agg = (
            select(
                EventRecord.event_type,
                func.count().label("cnt"),
                func.max(EventRecord.occurred_at).label("last_at"),
            )
            .where(and_(*ev_clauses))
            .group_by(EventRecord.event_type)
            .order_by(func.count().desc())
            .limit(_MAX_EVENT_TYPES_PER_ANCHOR)
        )
        agg_rows = (await session.execute(agg)).all()

        events_in_window = [
            CorrelationEventInWindow(
                event_type=str(et),
                count=int(cnt or 0),
                sample_occurred_at=last_at if last_at.tzinfo else last_at.replace(tzinfo=timezone.utc),
            )
            for et, cnt, last_at in agg_rows
        ]

        anchor_time = m.sampled_at
        if anchor_time.tzinfo is None:
            anchor_time = anchor_time.replace(tzinfo=timezone.utc)

        out_rows.append(
            CorrelationAnchorRow(
                host=host,
                anchor_time=anchor_time,
                cpu_at_anchor=float(m.value),
                events_in_window=events_in_window,
            )
        )

    return CpuEventCorrelationPayload(
        cpu_threshold_pct=threshold_pct,
        window_minutes=window_minutes,
        rows=out_rows,
    )
