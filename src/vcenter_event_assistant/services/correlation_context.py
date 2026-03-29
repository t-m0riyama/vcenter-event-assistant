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
    anchor_selection: Literal["threshold_met", "per_host_peak_fallback"] = Field(
        default="threshold_met",
        description=(
            "threshold_met: 閾値以上の raw サンプルからアンカーを選んだ。"
            "per_host_peak_fallback: 閾値を満たす行が無かったため、"
            "digest_context.high_cpu_hosts と同じ「ホスト別ピーク」で代替した"
        ),
    )
    rows: list[CorrelationAnchorRow]


async def _fetch_peak_cpu_per_host_samples(
    session: AsyncSession,
    from_utc: datetime,
    to_utc: datetime,
    vcenter_id: uuid.UUID | None,
    limit: int,
) -> list[MetricSample]:
    """
    ``digest_context`` の ``high_cpu_hosts`` と同じ定義（閾値なし）。

    期間内の各 (vcenter, entity_moid) について値が最大の 1 行を残し、
    値の降順で ``limit`` 件まで返す。
    """
    metric_clauses = [
        MetricSample.metric_key == METRIC_KEY_CPU_PCT,
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
        .where(and_(*metric_clauses))
    ).subquery()

    cpu_q = await session.execute(
        select(MetricSample)
        .join(cpu_rank, MetricSample.id == cpu_rank.c.id)
        .where(cpu_rank.c.rn == 1)
        .order_by(MetricSample.value.desc())
        .limit(limit),
    )
    return list(cpu_q.scalars().all())


def _dedupe_moids_take(samples: list[MetricSample], max_anchors: int) -> list[MetricSample]:
    """値の高い順に走査し、entity_moid ごとに最初の 1 行だけ採用して最大 ``max_anchors`` 件。"""
    seen_moids: set[str] = set()
    anchors: list[MetricSample] = []
    for s in samples:
        if s.entity_moid in seen_moids:
            continue
        seen_moids.add(s.entity_moid)
        anchors.append(s)
        if len(anchors) >= max_anchors:
            break
    return anchors


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

    - まず ``host.cpu.usage_pct`` で値が ``threshold_pct`` 以上のサンプルからアンカーを選ぶ。
    - **1 件も取れない場合**は ``digest_context.high_cpu_hosts`` と同じ「ホスト別ピーク」で代替する
      （グラフに変動があっても閾値未満だと空になっていた問題の回避）。
    - アンカーは ``entity_moid`` ごとに 1 件、最大 ``max_anchors`` 件。
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

    anchors = _dedupe_moids_take(m_rows, max_anchors)
    anchor_selection: Literal["threshold_met", "per_host_peak_fallback"] = "threshold_met"

    if not anchors:
        peak_rows = await _fetch_peak_cpu_per_host_samples(
            session, from_utc, to_utc, vcenter_id, max_anchors
        )
        anchors = [s for s in peak_rows if (s.entity_name or "").strip()][:max_anchors]
        if anchors:
            anchor_selection = "per_host_peak_fallback"

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
        anchor_selection=anchor_selection,
        rows=out_rows,
    )
