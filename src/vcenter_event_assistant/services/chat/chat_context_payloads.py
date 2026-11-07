"""チャット系 API で共有するコンテキスト生成。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import inspect

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.datetime_utils import to_utc
from vcenter_event_assistant.api.schemas.chat import ChatRequest, IncidentTimelineBuildRequest
from vcenter_event_assistant.services.chat.chat_event_time_buckets import (
    EventTimeBucketsPayload,
    build_chat_event_time_buckets,
)
from vcenter_event_assistant.services.chat.chat_context_timeline_entries import (
    build_chat_incident_timeline_entries,
)
from vcenter_event_assistant.services.chat.chat_incident_timeline import (
    IncidentTimelinePayload,
    build_chat_incident_timeline,
)
from vcenter_event_assistant.services.chat.chat_period_metrics import (
    PeriodMetricsPayload,
    build_chat_period_metrics,
    compute_chat_bucket_seconds,
)
from vcenter_event_assistant.services.digest.digest_context import DigestContext, build_digest_context
from vcenter_event_assistant.services.chat.aggregation_limiter import (
    AggregationBusy,
    AggregationLimitExceeded,
    aggregation_slot,
)
from vcenter_event_assistant.services.sql_time import truncate_to_second
from vcenter_event_assistant.settings_binding import require_settings


@dataclass(frozen=True)
class ChatContextPayloads:
    """チャット API が利用する集約済みのコンテキスト。"""

    context: DigestContext
    period_metrics: PeriodMetricsPayload | None
    event_time_buckets: EventTimeBucketsPayload | None
    incident_timeline: IncidentTimelinePayload


# 同時実行数の上限に達したときに、再試行までの目安として返す秒数。
_BUSY_RETRY_AFTER_SECONDS = 5


async def build_chat_context_payloads(
    session: AsyncSession,
    body: ChatRequest,
    *,
    owner_key: str,
) -> ChatContextPayloads:
    """チャット/プレビュー/タイムライン API 向けの共有ペイロードを生成する。

    ``owner_key`` は同時実行数を利用者ごとに数えるための識別子（``aggregation_owner_key``）。
    """
    return await _build_context_payloads_common(session, body, owner_key=owner_key)


async def _build_context_payloads_common(
    session: AsyncSession,
    body: ChatRequest | IncidentTimelineBuildRequest,
    *,
    owner_key: str,
) -> ChatContextPayloads:
    """メッセージ有無に依存せず共有コンテキストを構築する。

    期間内のイベントとメトリクスを集計する重い処理なので、同時実行数（利用者ごと・全体）に上限を設け、
    空きがなければ待たずに 503 を返す。イベントの集計行が多すぎるときは 422（Issue #301）。
    """
    # DB 側の時間バケットは秒単位なので、期間は入口で 1 回だけ秒に揃え、以降の集計すべてで同じ値を使う。
    # 400 の判定より前に揃えるのは、同じ秒の中の from/to を 400 で返すため（各集計の ValueError で 500 にしない）。
    ft = truncate_to_second(to_utc(body.from_time))
    tt = truncate_to_second(to_utc(body.to_time))
    if ft >= tt:
        raise HTTPException(
            status_code=400,
            detail="from は to より前である必要があります",
        )

    # サービス層なので bind 済みの Settings を直接読む（ルートの Depends(get_app_settings) の差し替えは効かない）。
    settings = require_settings()
    try:
        with aggregation_slot(
            owner_key,
            global_limit=settings.context_aggregation_concurrency,
            per_owner_limit=settings.context_aggregation_concurrency_per_user,
        ):
            return await _build_context_payloads_in_slot(
                session,
                body,
                ft,
                tt,
                max_rows=settings.context_aggregation_max_rows,
            )
    except AggregationBusy:
        raise HTTPException(
            status_code=503,
            detail="集計の処理が混み合っています。しばらく待ってから再度お試しください。",
            headers={"Retry-After": str(_BUSY_RETRY_AFTER_SECONDS)},
        ) from None
    except AggregationLimitExceeded:
        raise HTTPException(
            status_code=422,
            detail="イベントの種類が多すぎて集計できません。vCenter を指定して絞り込んでください。",
        ) from None


async def _build_context_payloads_in_slot(
    session: AsyncSession,
    body: ChatRequest | IncidentTimelineBuildRequest,
    ft: datetime,
    tt: datetime,
    *,
    max_rows: int,
) -> ChatContextPayloads:
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
            "max_rows": max_rows,
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

    timeline_entries = build_chat_incident_timeline_entries(
        context=ctx,
        timeline_event_time_buckets=timeline_event_time_buckets,
        timeline_period_metrics=timeline_period_metrics,
        include_period_metrics_cpu=body.include_period_metrics_cpu,
        include_period_metrics_memory=body.include_period_metrics_memory,
        include_period_metrics_disk_io=body.include_period_metrics_disk_io,
        include_period_metrics_network_io=body.include_period_metrics_network_io,
        metric_threshold_cpu_pct=body.metric_threshold_cpu_pct,
        metric_threshold_memory_pct=body.metric_threshold_memory_pct,
        metric_threshold_disk_pct=body.metric_threshold_disk_pct,
        metric_threshold_network_pct=body.metric_threshold_network_pct,
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
    *,
    owner_key: str,
) -> IncidentTimelinePayload:
    """タイムライン専用 API 用に incident_timeline を抽出して返す。"""
    payloads = await _build_context_payloads_common(session, body, owner_key=owner_key)
    return payloads.incident_timeline
