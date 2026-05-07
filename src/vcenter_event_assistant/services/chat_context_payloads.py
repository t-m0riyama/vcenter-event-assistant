"""チャット系 API で共有するコンテキスト生成。"""

from __future__ import annotations

from dataclasses import dataclass
import inspect

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.datetime_utils import to_utc
from vcenter_event_assistant.api.schemas.chat import ChatRequest, IncidentTimelineBuildRequest
from vcenter_event_assistant.services.chat_event_time_buckets import (
    EventTimeBucketsPayload,
    build_chat_event_time_buckets,
)
from vcenter_event_assistant.services.chat_incident_timeline import (
    IncidentTimelineEntry,
    IncidentTimelinePayload,
    build_chat_incident_timeline,
)
from vcenter_event_assistant.services.chat_period_metrics import (
    PeriodMetricsPayload,
    build_chat_period_metrics,
    compute_chat_bucket_seconds,
)
from vcenter_event_assistant.services.chat_timeline_metric_filter import (
    build_timeline_metric_entries,
)
from vcenter_event_assistant.services.digest_context import DigestContext, build_digest_context


@dataclass(frozen=True)
class ChatContextPayloads:
    """チャット API が利用する集約済みのコンテキスト。"""

    context: DigestContext
    period_metrics: PeriodMetricsPayload | None
    event_time_buckets: EventTimeBucketsPayload | None
    incident_timeline: IncidentTimelinePayload


async def build_chat_context_payloads(
    session: AsyncSession,
    body: ChatRequest,
) -> ChatContextPayloads:
    """チャット/プレビュー/タイムライン API 向けの共有ペイロードを生成する。"""
    return await _build_context_payloads_common(session, body)


async def _build_context_payloads_common(
    session: AsyncSession,
    body: ChatRequest | IncidentTimelineBuildRequest,
) -> ChatContextPayloads:
    """メッセージ有無に依存せず共有コンテキストを構築する。"""
    ft = to_utc(body.from_time)
    tt = to_utc(body.to_time)
    if ft >= tt:
        raise HTTPException(
            status_code=400,
            detail="from は to より前である必要があります",
        )

    ctx = await build_digest_context(
        session,
        ft,
        tt,
        top_notable_min_score=body.top_notable_min_score,
        vcenter_id=body.vcenter_id,
    )

    want_metrics = any(
        [
            body.include_period_metrics_cpu,
            body.include_period_metrics_memory,
            body.include_period_metrics_disk_io,
            body.include_period_metrics_network_io,
        ],
    )
    timeline_period_metrics: PeriodMetricsPayload | None = None
    timeline_event_time_buckets: EventTimeBucketsPayload | None = None
    timeline_bucket_sec: int | None = None
    if want_metrics:
        bucket_sec = compute_chat_bucket_seconds(ft, tt)
        timeline_bucket_sec = bucket_sec
        timeline_period_metrics = await build_chat_period_metrics(
            session,
            ft,
            tt,
            vcenter_id=body.vcenter_id,
            include_cpu=body.include_period_metrics_cpu,
            include_memory=body.include_period_metrics_memory,
            include_disk_io=body.include_period_metrics_disk_io,
            include_network_io=body.include_period_metrics_network_io,
            bucket_sec=bucket_sec,
        )
        event_bucket_kwargs = {
            "vcenter_id": body.vcenter_id,
            "bucket_sec": bucket_sec,
        }
        if "alert_top_n" in inspect.signature(build_chat_event_time_buckets).parameters:
            event_bucket_kwargs["alert_top_n"] = body.alert_top_n
        timeline_event_time_buckets = await build_chat_event_time_buckets(
            session,
            ft,
            tt,
            **event_bucket_kwargs,
        )

    period_metrics = None
    event_time_buckets = None
    if want_metrics and timeline_period_metrics is not None:
        period_metrics = PeriodMetricsPayload(
            bucket_minutes=timeline_period_metrics.bucket_minutes,
            from_utc=timeline_period_metrics.from_utc,
            to_utc=timeline_period_metrics.to_utc,
            cpu=timeline_period_metrics.cpu if body.include_period_metrics_cpu else None,
            memory=timeline_period_metrics.memory if body.include_period_metrics_memory else None,
            disk=timeline_period_metrics.disk if body.include_period_metrics_disk_io else None,
            network=timeline_period_metrics.network if body.include_period_metrics_network_io else None,
        )
        event_time_buckets = timeline_event_time_buckets

    timeline_entries: list[IncidentTimelineEntry] = []
    if timeline_event_time_buckets is not None:
        for row in timeline_event_time_buckets.buckets:
            for alert in getattr(row, "alert_top_types", []):
                timeline_entries.append(
                    IncidentTimelineEntry(
                        timestamp_utc=row.bucket_start_utc,
                        kind="alert",
                        title=f"{alert.event_type} ({alert.count}件, max score={alert.max_notable_score})",
                    )
                )
            alert_other_count = int(getattr(row, "alert_other_count", 0) or 0)
            if alert_other_count > 0:
                timeline_entries.append(
                    IncidentTimelineEntry(
                        timestamp_utc=row.bucket_start_utc,
                        kind="alert",
                        title=f"その他アラート ({alert_other_count}件)",
                    )
                )
    else:
        for g in ctx.top_notable_event_groups:
            timeline_entries.append(
                IncidentTimelineEntry(
                    timestamp_utc=g.occurred_at_last,
                    kind="alert",
                    title=f"{g.event_type} ({g.occurrence_count}件)",
                )
            )
    if timeline_event_time_buckets is not None:
        for row in timeline_event_time_buckets.buckets:
            timeline_entries.append(
                IncidentTimelineEntry(
                    timestamp_utc=row.bucket_start_utc,
                    kind="event",
                    title=f"イベント件数: {row.total}",
                )
            )
    else:
        for g in ctx.top_notable_event_groups:
            timeline_entries.append(
                IncidentTimelineEntry(
                    timestamp_utc=g.occurred_at_last,
                    kind="event",
                    title=f"関連イベント: {g.occurrence_count}件",
                )
            )
    if timeline_period_metrics is not None:
        selected_metric_series = [
            *((timeline_period_metrics.cpu or []) if body.include_period_metrics_cpu else []),
            *((timeline_period_metrics.memory or []) if body.include_period_metrics_memory else []),
            *((timeline_period_metrics.disk or []) if body.include_period_metrics_disk_io else []),
            *((timeline_period_metrics.network or []) if body.include_period_metrics_network_io else []),
        ]
        timeline_entries.extend(
            build_timeline_metric_entries(
                selected_metric_series,
                threshold_cpu_pct=body.metric_threshold_cpu_pct,
                threshold_memory_pct=body.metric_threshold_memory_pct,
                threshold_disk_pct=body.metric_threshold_disk_pct,
                threshold_network_pct=body.metric_threshold_network_pct,
            )
        )
    else:
        for row in ctx.high_cpu_hosts:
            timeline_entries.append(
                IncidentTimelineEntry(
                    timestamp_utc=row.sampled_at,
                    kind="metric",
                    title=f"host.cpu.usage_pct: {row.entity_name}={row.value:.2f}",
                )
            )
        for row in ctx.high_mem_hosts:
            timeline_entries.append(
                IncidentTimelineEntry(
                    timestamp_utc=row.sampled_at,
                    kind="metric",
                    title=f"host.mem.usage_pct: {row.entity_name}={row.value:.2f}",
                )
            )
    incident_timeline = build_chat_incident_timeline(
        timeline_entries,
        bucket_seconds=timeline_bucket_sec,
    )
    return ChatContextPayloads(
        context=ctx,
        period_metrics=period_metrics,
        event_time_buckets=event_time_buckets,
        incident_timeline=incident_timeline,
    )


async def build_incident_timeline_payload(
    session: AsyncSession,
    body: IncidentTimelineBuildRequest,
) -> IncidentTimelinePayload:
    """タイムライン専用 API 用に incident_timeline を抽出して返す。"""
    payloads = await _build_context_payloads_common(session, body)
    return payloads.incident_timeline
