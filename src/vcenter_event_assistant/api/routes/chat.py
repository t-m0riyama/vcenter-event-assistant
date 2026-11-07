"""期間コンテキスト付き LLM チャット API。"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.auth_deps import (
    AUTH_DISABLED_SOURCE,
    Principal,
    RequireOperator,
    check_principal_role,
    get_current_principal,
    principal_owner_key,
    refuse_if_principal_switched,
    resolve_request_principal,
)
from vcenter_event_assistant.api.deps import get_app_settings, get_session
from vcenter_event_assistant.api.schemas import (
    ChatAttachment,
    ChatPreviewResponse,
    ChatRequest,
    ChatResponse,
)
from vcenter_event_assistant.auth.roles import Role
from vcenter_event_assistant.auth.principal_header import PRINCIPAL_HEADER
from vcenter_event_assistant.db.session import get_session_factory
from vcenter_event_assistant.services.chat.chat_context_payloads import (
    build_chat_context_payloads,
)
from vcenter_event_assistant.services.chat.chat_llm import (
    build_chat_preview,
    run_period_chat,
)
from vcenter_event_assistant.services.llm.llm_profile import is_chat_llm_configured
from vcenter_event_assistant.services.llm.llm_tracing import build_llm_runnable_config
from vcenter_event_assistant.services.research.research_attach import (
    build_research_attachment_markdown,
)
from vcenter_event_assistant.services.vcenter_labels import (
    load_all_vcenter_anonymization_strings,
)
from vcenter_event_assistant.settings import Settings


class _ChatRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            settings = get_app_settings()
            if settings.auth_enabled:
                # FastAPI は依存関係より先に JSON を読む。ここでは先に権限だけ確認する。
                # 受信中に権限が変わり得るため、解析後の RequireOperator でも再確認する。
                async with get_session_factory(settings=settings)() as db:
                    principal = await resolve_request_principal(request, db, settings, touch=False)
                    check_principal_role(principal, Role.OPERATOR)
            else:
                # 認証付きで開いた古いタブから、認証無効に変わった配備へ送らせない。
                marker = f"auth-{AUTH_DISABLED_SOURCE}"
                try:
                    refuse_if_principal_switched(request, marker)
                except HTTPException as exc:
                    # 認証無効時は PrincipalHeaderMiddleware がないため、拒否応答に直接付ける。
                    exc.headers = {PRINCIPAL_HEADER.decode("ascii"): marker}
                    raise
            return await handler(request)

        return handle


router = APIRouter(prefix="/chat", tags=["chat"], route_class=_ChatRoute)


def _accepted_attachments(
    body: ChatRequest, settings: Settings
) -> list[ChatAttachment]:
    """設定上の上限を適用した添付リストを返す。

    件数超過は 422。テキストの文字数超過は切り詰めて受け付ける
    （通常はクライアント側で済んでいる。API を直接叩く経路への保険）。
    """
    attachments = list(body.attachments)
    if not attachments:
        return []
    max_files = settings.chat_attachment_max_files
    if max_files <= 0:
        raise HTTPException(status_code=422, detail="ファイルの添付は無効化されています")
    if len(attachments) > max_files:
        raise HTTPException(
            status_code=422,
            detail=f"添付できるファイルは {max_files} 件までです（{len(attachments)} 件）",
        )

    max_chars = settings.chat_attachment_max_text_chars
    out: list[ChatAttachment] = []
    for a in attachments:
        if a.kind == "text" and a.text is not None and len(a.text) > max_chars:
            out.append(a.model_copy(update={"text": a.text[:max_chars], "truncated": True}))
        else:
            out.append(a)
    return out


@router.post("", dependencies=[RequireOperator], response_model=ChatResponse)
async def post_chat(
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(get_current_principal),
) -> ChatResponse:
    if not is_chat_llm_configured(settings):
        raise HTTPException(
            status_code=503,
            detail=(
                "LLM が未設定です。環境変数 LLM_DIGEST_API_KEY または LLM_CHAT_API_KEY を設定するか、"
                "Copilot CLI チャットで LLM_COPILOT_CLI_SESSION_AUTH=true（gh auth login 済み）にしてください。"
            ),
        )

    attachments = _accepted_attachments(body, settings)
    payloads = await build_chat_context_payloads(
        session, body, owner_key=principal_owner_key(principal)
    )

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
        settings=settings,
        enable_web_search=body.enable_web_search,
        web_search_scope=body.web_search_scope,
        web_search_aggressiveness=body.web_search_aggressiveness,
        attachments=attachments,
    )

    # 関連調査情報は LLM 応答の後にサーバ側で連結する（LLM プロンプトには混ぜない）。
    if err is None and body.include_research:
        research_md = await build_research_attachment_markdown(
            session,
            from_utc=body.from_time,
            to_utc=body.to_time,
            settings=settings,
        )
        if research_md:
            text = text.rstrip() + "\n\n" + research_md

    return ChatResponse(
        assistant_content=text,
        error=err,
        llm_context=llm_meta,
        created_at=datetime.now(timezone.utc),
        latency_ms=latency_ms,
        token_per_sec=token_per_sec,
    )


@router.post("/preview", dependencies=[RequireOperator], response_model=ChatPreviewResponse)
async def post_chat_preview(
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(get_current_principal),
) -> ChatPreviewResponse:
    if not settings.effective_chat_preview_enabled:
        raise HTTPException(status_code=404, detail="Chat preview API is disabled")

    attachments = _accepted_attachments(body, settings)
    payloads = await build_chat_context_payloads(
        session, body, owner_key=principal_owner_key(principal)
    )

    vc_anon = await load_all_vcenter_anonymization_strings(session)
    preview_settings = settings
    if settings.is_production:
        preview_settings = settings.model_copy(update={"llm_anonymization_enabled": True})
    block, trimmed, meta = build_chat_preview(
        context=payloads.context,
        messages=list(body.messages),
        period_metrics=payloads.period_metrics,
        event_time_buckets=payloads.event_time_buckets,
        incident_timeline=payloads.incident_timeline,
        extra_vcenter_strings=vc_anon,
        settings=preview_settings,
        attachments=attachments,
    )
    return ChatPreviewResponse(
        context_block=block,
        conversation=trimmed,
        llm_context=meta,
        incident_timeline=payloads.incident_timeline,
    )
