"""期間コンテキスト付き LLM チャット API。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.datetime_utils import to_utc
from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas import ChatPreviewResponse, ChatRequest, ChatResponse
from vcenter_event_assistant.services.chat_event_time_buckets import build_chat_event_time_buckets, EventTimeBucketsPayload
from vcenter_event_assistant.services.chat_incident_timeline import (
    build_chat_incident_timeline,
    IncidentTimelineEntry,
    IncidentTimelinePayload,
)
from vcenter_event_assistant.services.chat_llm import build_chat_preview, run_period_chat
from vcenter_event_assistant.services.chat_period_metrics import (
    build_chat_period_metrics,
    compute_chat_bucket_seconds,
    PeriodMetricsPayload,
)
from vcenter_event_assistant.services.digest_context import build_digest_context, DigestContext
from vcenter_event_assistant.services.llm_profile import is_chat_llm_configured
from vcenter_event_assistant.services.vcenter_labels import load_all_vcenter_anonymization_strings
from vcenter_event_assistant.services.llm_tracing import build_llm_runnable_config
from vcenter_event_assistant.settings import get_settings

router = APIRouter(prefix="/chat", tags=["chat"])


async def _build_chat_context_payloads(
    session: AsyncSession,
    body: ChatRequest,
) -> tuple[DigestContext, PeriodMetricsPayload | None, EventTimeBucketsPayload | None, IncidentTimelinePayload]:
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
    if want_metrics:
        bucket_sec = compute_chat_bucket_seconds(ft, tt)
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
        timeline_event_time_buckets = await build_chat_event_time_buckets(
            session,
            ft,
            tt,
            vcenter_id=body.vcenter_id,
            bucket_sec=bucket_sec,
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
        for series in selected_metric_series:
            for point in series.series:
                timeline_entries.append(
                    IncidentTimelineEntry(
                        timestamp_utc=point.bucket_start_utc,
                        kind="metric",
                        title=f"{series.metric_key}: avg={point.avg:.2f}",
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
    incident_timeline = build_chat_incident_timeline(timeline_entries)
    return ctx, period_metrics, event_time_buckets, incident_timeline


@router.post("", response_model=ChatResponse)
async def post_chat(
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
) -> ChatResponse:
    settings = get_settings()
    if not is_chat_llm_configured(settings):
        raise HTTPException(
            status_code=503,
            detail=(
                "LLM が未設定です。環境変数 LLM_DIGEST_API_KEY または LLM_CHAT_API_KEY を設定するか、"
                "Copilot CLI チャットで LLM_COPILOT_CLI_SESSION_AUTH=true（gh auth login 済み）にしてください。"
            ),
        )

    ctx, period_metrics, event_time_buckets, incident_timeline = await _build_chat_context_payloads(session, body)

    llm_cfg = build_llm_runnable_config(
        settings,
        run_kind="period_chat",
        vcenter_id=str(body.vcenter_id) if body.vcenter_id is not None else None,
    )
    vc_anon = await load_all_vcenter_anonymization_strings(session)
    text, err, llm_meta, latency_ms, token_per_sec = await run_period_chat(
        context=ctx,
        messages=list(body.messages),
        period_metrics=period_metrics,
        event_time_buckets=event_time_buckets,
        incident_timeline=incident_timeline,
        runnable_config=llm_cfg,
        extra_vcenter_strings=vc_anon,
    )
    return ChatResponse(
        assistant_content=text,
        error=err,
        llm_context=llm_meta,
        created_at=datetime.now(timezone.utc),
        latency_ms=latency_ms,
        token_per_sec=token_per_sec,
    )


@router.post("/preview", response_model=ChatPreviewResponse)
async def post_chat_preview(
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
) -> ChatPreviewResponse:
    ctx, period_metrics, event_time_buckets, incident_timeline = await _build_chat_context_payloads(session, body)

    vc_anon = await load_all_vcenter_anonymization_strings(session)
    block, trimmed, meta = build_chat_preview(
        context=ctx,
        messages=list(body.messages),
        period_metrics=period_metrics,
        event_time_buckets=event_time_buckets,
        incident_timeline=incident_timeline,
        extra_vcenter_strings=vc_anon,
    )
    return ChatPreviewResponse(
        context_block=block,
        conversation=trimmed,
        llm_context=meta,
        incident_timeline=incident_timeline,
    )
