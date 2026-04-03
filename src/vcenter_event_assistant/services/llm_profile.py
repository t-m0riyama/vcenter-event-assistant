"""ダイジェスト用とチャット用の実効 LLM 設定を解決する。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from vcenter_event_assistant.settings import LlmProvider, Settings

LlmPurpose = Literal["digest", "chat"]


@dataclass(frozen=True)
class ResolvedLlmProfile:
    """``build_chat_model`` に渡す実効プロバイダ・接続パラメータ。"""

    provider: LlmProvider
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float


def effective_chat_api_key(settings: Settings) -> str:
    """
    チャット API で用いる実効 API キー（strip 済み）。

    ``llm_chat_api_key`` が非空ならそれを、否则 ``llm_digest_api_key`` を返す。
    両方空なら空文字。
    """
    chat = (settings.llm_chat_api_key or "").strip()
    if chat:
        return chat
    return (settings.llm_digest_api_key or "").strip()


def resolve_llm_profile(settings: Settings, *, purpose: LlmPurpose) -> ResolvedLlmProfile:
    """
    ``purpose`` に応じた実効プロファイルを返す。

    - ``digest``: ``LLM_DIGEST_*`` のみ（チャット上書きは使わない）。
    - ``chat``: ``LLM_CHAT_*`` をフィールド単位で適用し、未設定は ``LLM_DIGEST_*`` にフォールバック。
    """
    if purpose == "digest":
        return ResolvedLlmProfile(
            provider=settings.llm_digest_provider,
            api_key=(settings.llm_digest_api_key or "").strip(),
            base_url=settings.llm_digest_base_url,
            model=settings.llm_digest_model,
            timeout_seconds=settings.llm_digest_timeout_seconds,
        )

    prov: LlmProvider = (
        settings.llm_chat_provider
        if settings.llm_chat_provider is not None
        else settings.llm_digest_provider
    )
    api_key = effective_chat_api_key(settings)
    base = (settings.llm_chat_base_url or "").strip() or settings.llm_digest_base_url
    model = (settings.llm_chat_model or "").strip() or settings.llm_digest_model
    timeout = (
        settings.llm_chat_timeout_seconds
        if settings.llm_chat_timeout_seconds is not None
        else settings.llm_digest_timeout_seconds
    )
    return ResolvedLlmProfile(
        provider=prov,
        api_key=api_key,
        base_url=base,
        model=model,
        timeout_seconds=timeout,
    )
