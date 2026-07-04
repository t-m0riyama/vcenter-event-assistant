"""期間コンテキスト付き LLM チャット API。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas import ChatPreviewResponse, ChatRequest, ChatResponse
from vcenter_event_assistant.services.chat.chat_context_payloads import build_chat_context_payloads
from vcenter_event_assistant.services.chat.chat_llm import build_chat_preview, run_period_chat
from vcenter_event_assistant.services.llm.llm_profile import is_chat_llm_configured
from vcenter_event_assistant.services.vcenter_labels import load_all_vcenter_anonymization_strings
from vcenter_event_assistant.services.llm.llm_tracing import build_llm_runnable_config
from vcenter_event_assistant.settings import get_settings

router = APIRouter(prefix="/chat", tags=["chat"])


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

    payloads = await build_chat_context_payloads(session, body)

    llm_cfg = build_llm_runnable_config(
        settings,
        run_kind="period_chat",
        vcenter_id=str(body.vcenter_id) if body.vcenter_id is not None else None,
    )
    vc_anon = await load_all_vcenter_anonymization_strings(session)
    text, err, llm_meta, latency_ms, token_per_sec = await run_period_chat(
        context=payloads.context,
        messages=list(body.messages),
        period_metrics=payloads.period_metrics,
        event_time_buckets=payloads.event_time_buckets,
        incident_timeline=payloads.incident_timeline,
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
    payloads = await build_chat_context_payloads(session, body)

    vc_anon = await load_all_vcenter_anonymization_strings(session)
    block, trimmed, meta = build_chat_preview(
        context=payloads.context,
        messages=list(body.messages),
        period_metrics=payloads.period_metrics,
        event_time_buckets=payloads.event_time_buckets,
        incident_timeline=payloads.incident_timeline,
        extra_vcenter_strings=vc_anon,
    )
    return ChatPreviewResponse(
        context_block=block,
        conversation=trimmed,
        llm_context=meta,
        incident_timeline=payloads.incident_timeline,
    )
