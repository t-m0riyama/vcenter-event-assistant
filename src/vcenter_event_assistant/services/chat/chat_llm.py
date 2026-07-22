"""期間集約コンテキストを用いたチャット用 LLM 呼び出し（LangChain: OpenAI 互換または Gemini）。"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from vcenter_event_assistant.api.schemas import ChatLlmContextMeta, ChatMessage
from vcenter_event_assistant.services.chat.chat_event_time_buckets import (
    EventTimeBucketsPayload,
)
from vcenter_event_assistant.services.chat.chat_incident_timeline import (
    IncidentTimelinePayload,
)
from vcenter_event_assistant.services.chat.chat_llm_payload import (
    CHAT_SYSTEM_PROMPT,
    build_chat_llm_context,
    compose_chat_system_prompt,
)
from vcenter_event_assistant.services.chat.chat_period_metrics import (
    PeriodMetricsPayload,
)
from vcenter_event_assistant.services.chat.chat_web_search import (
    render_web_search_sources,
    run_chat_with_web_search,
    run_copilot_chat_with_web_search,
)
from vcenter_event_assistant.services.digest.digest_context import DigestContext
from vcenter_event_assistant.services.llm.llm_anonymization import deanonymize_text
from vcenter_event_assistant.services.research.search_provider import (
    WebSearchResult,
    build_search_provider,
)
from vcenter_event_assistant.services.llm.llm_user_errors import (
    _llm_failure_detail_for_user,
)
from vcenter_event_assistant.services.llm.copilot_cli_llm import (
    run_copilot_cli_chat_completion,
)
from vcenter_event_assistant.services.llm.llm_factory import build_chat_model
from vcenter_event_assistant.services.llm.llm_profile import (
    is_chat_llm_configured,
    resolve_llm_profile,
)
from vcenter_event_assistant.services.llm.llm_invoke import (
    log_llm_failure,
    stream_chat_to_text,
)
from vcenter_event_assistant.settings import Settings
from vcenter_event_assistant.settings_binding import require_settings

_logger = logging.getLogger(__name__)

# 後方互換: 既存テストが chat_llm から参照
_CHAT_SYSTEM_PROMPT = CHAT_SYSTEM_PROMPT


def _to_langchain_messages(
    block: str,
    trimmed: list[ChatMessage],
    *,
    system_prompt: str | None = None,
) -> list[BaseMessage]:
    """システム・コンテキスト JSON ブロック・会話履歴を LangChain メッセージ列に変換する。"""
    out: list[BaseMessage] = [
        SystemMessage(content=system_prompt if system_prompt is not None else CHAT_SYSTEM_PROMPT),
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
    settings: Settings | None = None,
) -> tuple[str, list[ChatMessage], ChatLlmContextMeta | None]:
    """
    LLM API を呼び出さずに、送出するコンテキストブロックと会話履歴を準備する。
    Returns:
        (context_block_string, trimmed_messages, llm_context_meta)
    """
    s = settings or require_settings()
    block, trimmed, meta, _ = build_chat_llm_context(
        context,
        messages,
        period_metrics,
        event_time_buckets,
        incident_timeline,
        extra_vcenter_strings,
        settings=s,
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
    settings: Settings | None = None,
    enable_web_search: bool = False,
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
    s = settings or require_settings()
    if not is_chat_llm_configured(s):
        return ("", None, None, None, None)

    block, trimmed, meta, reverse_map = build_chat_llm_context(
        context,
        messages,
        period_metrics,
        event_time_buckets,
        incident_timeline,
        extra_vcenter_strings,
        settings=s,
    )

    try:
        cprof = resolve_llm_profile(s, purpose="chat")
        _logger.info(
            "chat LLM リクエスト est_input_tokens=%s json_chars=%s json_truncated=%s message_turns=%s "
            "timeout_seconds=%s model=%s max_input_tokens=%s",
            meta.estimated_input_tokens,
            len(block),
            meta.json_truncated,
            meta.message_turns,
            cprof.timeout_seconds,
            cprof.model,
            s.llm_chat_max_input_tokens,
        )
        web_search_provider = build_search_provider(s) if enable_web_search else None
        # ツールが実際にバインドされるときだけ検索指針をシステムプロンプトへ付与する
        system_prompt = compose_chat_system_prompt(
            enable_web_search=web_search_provider is not None
        )
        web_sources: list[WebSearchResult] = []
        if cprof.provider == "copilot_cli":
            start_time = time.perf_counter()
            if web_search_provider is not None:
                text, web_sources = await run_copilot_chat_with_web_search(
                    s,
                    system_prompt=system_prompt,
                    block=block,
                    messages=trimmed,
                    provider=web_search_provider,
                )
            else:
                text = await run_copilot_cli_chat_completion(
                    s,
                    system_prompt=system_prompt,
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
            model = build_chat_model(s, purpose="chat", config=runnable_config)
            lc_messages = _to_langchain_messages(
                block, trimmed, system_prompt=system_prompt
            )
            if web_search_provider is not None:
                start_time = time.perf_counter()
                text, web_sources = await run_chat_with_web_search(
                    model,
                    lc_messages,
                    web_search_provider,
                    s,
                    config=runnable_config,
                )
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                token_per_sec = None
            else:
                text, latency_ms, token_per_sec = await stream_chat_to_text(
                    model, lc_messages, config=runnable_config
                )
        text = deanonymize_text(text.strip(), reverse_map)
        # 出典は実際のツール実行結果からサーバ側で連結（LLM 出力の URL は一次情報にしない）
        sources_block = render_web_search_sources(web_sources)
        if sources_block:
            text = text.rstrip() + "\n\n" + sources_block
        return (text, None, meta, latency_ms, token_per_sec)
    except Exception as e:
        log_llm_failure(s, "chat", e)
        detail = _llm_failure_detail_for_user(e)
        return ("", f"チャット応答を取得できませんでした（{detail}）", meta, None, None)
