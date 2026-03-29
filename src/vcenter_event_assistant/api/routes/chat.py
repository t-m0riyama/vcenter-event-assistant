"""期間コンテキスト付き LLM チャット API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.datetime_utils import to_utc
from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas import ChatRequest, ChatResponse
from vcenter_event_assistant.services.chat_llm import run_period_chat
from vcenter_event_assistant.services.chat_period_metrics import build_chat_period_metrics
from vcenter_event_assistant.services.digest_context import build_digest_context
from vcenter_event_assistant.settings import get_settings

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def post_chat(
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
) -> ChatResponse:
    settings = get_settings()
    if not (settings.llm_api_key or "").strip():
        raise HTTPException(
            status_code=503,
            detail="LLM が未設定です。環境変数 LLM_API_KEY を設定してください。",
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
    if want_metrics:
        period_metrics = await build_chat_period_metrics(
            session,
            ft,
            tt,
            vcenter_id=body.vcenter_id,
            include_cpu=body.include_period_metrics_cpu,
            include_memory=body.include_period_metrics_memory,
            include_disk_io=body.include_period_metrics_disk_io,
            include_network_io=body.include_period_metrics_network_io,
        )

    text, err, llm_meta = await run_period_chat(
        settings,
        context=ctx,
        messages=list(body.messages),
        period_metrics=period_metrics,
    )
    return ChatResponse(assistant_content=text, error=err, llm_context=llm_meta)
