"""期間コンテキスト付き LLM チャット API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.datetime_utils import to_utc
from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas import ChatRequest, ChatResponse
from vcenter_event_assistant.services.chat_event_time_buckets import build_chat_event_time_buckets
from vcenter_event_assistant.services.chat_llm import run_period_chat
from vcenter_event_assistant.services.chat_period_metrics import (
    build_chat_period_metrics,
    compute_chat_bucket_seconds,
)
from vcenter_event_assistant.services.digest_context import build_digest_context
from vcenter_event_assistant.services.llm_profile import effective_chat_api_key
from vcenter_event_assistant.services.llm_tracing import build_llm_runnable_config
from vcenter_event_assistant.settings import get_settings

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def post_chat(
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
) -> ChatResponse:
    settings = get_settings()
    if not effective_chat_api_key(settings):
        raise HTTPException(
            status_code=503,
            detail=(
                "LLM が未設定です。環境変数 LLM_DIGEST_API_KEY または LLM_CHAT_API_KEY を設定してください。"
            ),
        )

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
    period_metrics = None
    event_time_buckets = None
    if want_metrics:
        bucket_sec = compute_chat_bucket_seconds(ft, tt)
        period_metrics = await build_chat_period_metrics(
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
        event_time_buckets = await build_chat_event_time_buckets(
            session,
            ft,
            tt,
            vcenter_id=body.vcenter_id,
            bucket_sec=bucket_sec,
        )

    llm_cfg = build_llm_runnable_config(
        settings,
        run_kind="period_chat",
        vcenter_id=str(body.vcenter_id) if body.vcenter_id is not None else None,
    )
    text, err, llm_meta = await run_period_chat(
        settings,
        context=ctx,
        messages=list(body.messages),
        period_metrics=period_metrics,
        event_time_buckets=event_time_buckets,
        runnable_config=llm_cfg,
    )
    return ChatResponse(assistant_content=text, error=err, llm_context=llm_meta)
