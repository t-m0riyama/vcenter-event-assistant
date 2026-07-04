"""期間集約コンテキストを用いたチャット用 LLM 呼び出し（LangChain: OpenAI 互換または Gemini）。"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from vcenter_event_assistant.api.schemas import ChatLlmContextMeta, ChatMessage
from vcenter_event_assistant.services.chat.chat_event_time_buckets import EventTimeBucketsPayload
from vcenter_event_assistant.services.chat.chat_incident_timeline import IncidentTimelinePayload
from vcenter_event_assistant.services.chat.chat_llm_payload import (
    CHAT_SYSTEM_PROMPT,
    build_chat_llm_context,
)
from vcenter_event_assistant.services.chat.chat_period_metrics import PeriodMetricsPayload
from vcenter_event_assistant.services.digest.digest_context import DigestContext
from vcenter_event_assistant.services.llm.llm_anonymization import deanonymize_text
from vcenter_event_assistant.services.llm.llm_user_errors import _llm_failure_detail_for_user
from vcenter_event_assistant.services.llm.copilot_cli_llm import run_copilot_cli_chat_completion
from vcenter_event_assistant.services.llm.llm_factory import build_chat_model
from vcenter_event_assistant.services.llm.llm_profile import (
    is_chat_llm_configured,
    resolve_llm_profile,
)
from vcenter_event_assistant.services.llm.llm_invoke import log_llm_failure, stream_chat_to_text
from vcenter_event_assistant.settings import get_settings

_logger = logging.getLogger(__name__)

# 後方互換: 既存テストが chat_llm から参照
_CHAT_SYSTEM_PROMPT = CHAT_SYSTEM_PROMPT


def _to_langchain_messages(block: str, trimmed: list[ChatMessage]) -> list[BaseMessage]:
    """システム・コンテキスト JSON ブロック・会話履歴を LangChain メッセージ列に変換する。"""
    out: list[BaseMessage] = [
        SystemMessage(content=CHAT_SYSTEM_PROMPT),
        HumanMessage(content=block),
    ]
    for m in trimmed:
        if m.role == "user":
            out.append(HumanMessage(content=m.content))
        else:
            out.append(AIMessage(content=m.content))
    return out


def build_chat_preview(
    *,
    context: DigestContext,
    messages: list[ChatMessage],
    period_metrics: PeriodMetricsPayload | None = None,
    event_time_buckets: EventTimeBucketsPayload | None = None,
    incident_timeline: IncidentTimelinePayload | None = None,
    extra_vcenter_strings: Sequence[str] | None = None,
) -> tuple[str, list[ChatMessage], ChatLlmContextMeta | None]:
    """
    LLM API を呼び出さずに、送出するコンテキストブロックと会話履歴を準備する。
    Returns:
        (context_block_string, trimmed_messages, llm_context_meta)
    """
    block, trimmed, meta, _ = build_chat_llm_context(
        context,
        messages,
        period_metrics,
        event_time_buckets,
        incident_timeline,
        extra_vcenter_strings,
        settings=get_settings(),
    )
    return block, trimmed, meta


async def run_period_chat(
    *,
    context: DigestContext,
    messages: list[ChatMessage],
    period_metrics: PeriodMetricsPayload | None = None,
    event_time_buckets: EventTimeBucketsPayload | None = None,
    incident_timeline: IncidentTimelinePayload | None = None,
    runnable_config: RunnableConfig | None = None,
    extra_vcenter_strings: Sequence[str] | None = None,
) -> tuple[str, str | None, ChatLlmContextMeta | None, int | None, float | None]:
    """
    集約 JSON と会話履歴を渡して LLM の応答本文を返す。

    ``period_metrics`` / ``event_time_buckets`` を渡すと ``digest_context`` とマージした JSON を入力とする。
    チャットでは ``digest_context`` からホスト別 CPU/メモリピーク（``high_cpu_hosts`` / ``high_mem_hosts``）を除く。

    ``runnable_config`` は将来 LangSmith 等の callbacks を渡すための拡張点（未使用でもよい）。

    ``extra_vcenter_strings`` に DB 登録済み vCenter の表示名・接続 host 等を渡すと、
    匿名化有効時に会話本文からもトークン化する（API ルートでは全件読込を渡す）。

    Returns:
        (assistant_text, error_message, llm_context_meta, latency_ms, token_per_sec)。
        チャット LLM が未設定のとき（``is_chat_llm_configured`` が False）は ("", None, None, None, None)。
        LLM 呼び出し前までに確定する統計は、HTTP 失敗時も第 3 要素に返す。
    """
    settings = get_settings()
    if not is_chat_llm_configured(settings):
        return ("", None, None, None, None)

    block, trimmed, meta, reverse_map = build_chat_llm_context(
        context,
        messages,
        period_metrics,
        event_time_buckets,
        incident_timeline,
        extra_vcenter_strings,
        settings=settings,
    )

    try:
        cprof = resolve_llm_profile(settings, purpose="chat")
        _logger.info(
            "chat LLM リクエスト est_input_tokens=%s json_chars=%s json_truncated=%s message_turns=%s "
            "timeout_seconds=%s model=%s max_input_tokens=%s",
            meta.estimated_input_tokens,
            len(block),
            meta.json_truncated,
            meta.message_turns,
            cprof.timeout_seconds,
            cprof.model,
            settings.llm_chat_max_input_tokens,
        )
        if cprof.provider == "copilot_cli":
            start_time = time.perf_counter()
            text = await run_copilot_cli_chat_completion(
                settings,
                system_prompt=CHAT_SYSTEM_PROMPT,
                block=block,
                messages=trimmed,
            )
            end_time = time.perf_counter()
            latency_ms = int((end_time - start_time) * 1000)
            token_per_sec = None
            duration_sec = end_time - start_time
            if duration_sec > 0:
                try:
                    import tiktoken
                    enc = tiktoken.get_encoding("cl100k_base")
                    token_per_sec = round(len(enc.encode(text)) / duration_sec, 1)
                except Exception:
                    pass
        else:
            model = build_chat_model(settings, purpose="chat", config=runnable_config)
            lc_messages = _to_langchain_messages(block, trimmed)
            text, latency_ms, token_per_sec = await stream_chat_to_text(model, lc_messages, config=runnable_config)
        text = deanonymize_text(text.strip(), reverse_map)
        return (text, None, meta, latency_ms, token_per_sec)
    except Exception as e:
        log_llm_failure(settings, "chat", e)
        detail = _llm_failure_detail_for_user(e)
        return ("", f"チャット応答を取得できませんでした（{detail}）", meta, None, None)
