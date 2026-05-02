"""LangChain ChatModel のストリーミング呼び出し（共通）。"""

from __future__ import annotations

import logging
import time
import tiktoken
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig

from vcenter_event_assistant.services.llm_profile import resolve_llm_profile
from vcenter_event_assistant.settings import Settings

_logger = logging.getLogger(__name__)


def log_llm_failure(
    settings: Settings,
    purpose: str,
    exc: BaseException,
) -> None:
    """LLM 呼び出し失敗の運用ログ（API キーは出力しない）。"""
    prof = resolve_llm_profile(settings, purpose=purpose)
    if prof.provider == "openai_compatible":
        base = (prof.base_url or "").rstrip("/")
        _logger.warning(
            "%s LLM 呼び出しに失敗 provider=openai_compatible base_url=%s model=%s exc=%r",
            purpose, base, prof.model, exc, exc_info=True,
        )
    elif prof.provider == "copilot_cli":
        _logger.warning(
            "%s LLM 呼び出しに失敗 provider=copilot_cli model=%s exc=%r",
            purpose, prof.model, exc, exc_info=True,
        )
    else:
        _logger.warning(
            "%s LLM 呼び出しに失敗 provider=gemini model=%s exc=%r",
            purpose, prof.model, exc, exc_info=True,
        )


async def stream_chat_to_text(
    model: BaseChatModel,
    messages: list[BaseMessage],
    *,
    config: RunnableConfig | None = None,
) -> tuple[str, int | None, float | None]:
    """
    ``astream`` でチャンクを連結し、assistant 本文と (latency_ms, token_per_sec) を返す。

    Ollama 等の長い生成では非ストリーミングが打ち切られることがあるためストリーミングを使う。
    一部プロバイダでは ``content`` が文字列ではなくテキストブロックの配列になるため、
    ``str(content)`` は使わず ``text`` で抽出する。
    """
    parts: list[str] = []
    start_time = time.perf_counter()
    first_token_time = None

    async for chunk in model.astream(messages, config=config):
        if chunk.content:
            if first_token_time is None:
                first_token_time = time.perf_counter()
            parts.append(str(chunk.text))

    end_time = time.perf_counter()
    text = "".join(parts).strip()
    if not text:
        raise ValueError("LLM ストリーミング応答に assistant 本文がありません（内容が空）")

    latency_ms = None
    if first_token_time is not None:
        latency_ms = int((first_token_time - start_time) * 1000)

    token_per_sec = None
    if first_token_time is not None and end_time > first_token_time:
        duration_sec = end_time - first_token_time
        try:
            enc = tiktoken.get_encoding("cl100k_base")
            out_tokens = len(enc.encode(text))
            if duration_sec > 0:
                token_per_sec = round(out_tokens / duration_sec, 1)
        except Exception:
            pass

    return text, latency_ms, token_per_sec
