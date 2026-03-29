"""期間コンテキスト付き LLM チャット API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.datetime_utils import to_utc
from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas import ChatRequest, ChatResponse
from vcenter_event_assistant.services.chat_llm import run_period_chat
from vcenter_event_assistant.services.correlation_context import build_cpu_event_correlation
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

    correlation = None
    if body.include_cpu_event_correlation:
        # rows が空でもペイロードを渡す（LLM が「キーが無い」と誤解しないようにする）
        correlation = await build_cpu_event_correlation(
            session,
            ft,
            tt,
            vcenter_id=body.vcenter_id,
            threshold_pct=body.cpu_correlation_threshold_pct,
            window_minutes=body.cpu_correlation_window_minutes,
            max_anchors=20,
        )

    text, err, llm_meta = await run_period_chat(
        settings,
        context=ctx,
        messages=list(body.messages),
        correlation=correlation,
    )
    return ChatResponse(assistant_content=text, error=err, llm_context=llm_meta)
