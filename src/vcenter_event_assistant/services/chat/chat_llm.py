"""期間集約コンテキストを用いたチャット用 LLM 呼び出し（LangChain: OpenAI 互換または Gemini）。"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from vcenter_event_assistant.api.schemas import (
    ChatAttachment,
    ChatLlmContextMeta,
    ChatMessage,
)
from vcenter_event_assistant.services.chat.chat_event_time_buckets import (
    EventTimeBucketsPayload,
)
from vcenter_event_assistant.services.chat.chat_incident_timeline import (
    IncidentTimelinePayload,
)
from vcenter_event_assistant.services.chat.chat_llm_payload import (
    CHAT_SYSTEM_PROMPT,
    DEFAULT_WEB_SEARCH_AGGRESSIVENESS,
    DEFAULT_WEB_SEARCH_SCOPE,
    WebSearchAggressiveness,
    WebSearchScope,
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
    chat_provider_supports_images,
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
    attachment_block: str | None = None,
    images: Sequence[ChatAttachment] | None = None,
) -> list[BaseMessage]:
    """システム・コンテキスト JSON ブロック・添付・会話履歴を LangChain メッセージ列に変換する。

    画像は最後の user メッセージのマルチモーダル content に載せる
    （``ChatOpenAI`` / ``ChatGoogleGenerativeAI`` いずれもこの形を受ける）。
    """
    out: list[BaseMessage] = [
        SystemMessage(content=system_prompt if system_prompt is not None else CHAT_SYSTEM_PROMPT),
        HumanMessage(content=block),
    ]
    if attachment_block:
        out.append(HumanMessage(content=attachment_block))

    image_list = list(images or [])
    last_user_index = _last_user_message_index(trimmed)
    for i, m in enumerate(trimmed):
        if m.role != "user":
            out.append(AIMessage(content=m.content))
        elif image_list and i == last_user_index:
            out.append(HumanMessage(content=_multimodal_content(m.content, image_list)))
        else:
            out.append(HumanMessage(content=m.content))

    if image_list and last_user_index is None:
        # 会話が予算で全て落ちた場合でも画像は渡す
        out.append(HumanMessage(content=_multimodal_content("", image_list)))
    return out


def _last_user_message_index(trimmed: Sequence[ChatMessage]) -> int | None:
    """最後の user メッセージの位置（無ければ None）。"""
    for i in range(len(trimmed) - 1, -1, -1):
        if trimmed[i].role == "user":
            return i
    return None


def _multimodal_content(
    text: str, images: Sequence[ChatAttachment]
) -> list[dict[str, object]]:
    """テキスト + 画像のマルチモーダル content ブロックを組み立てる。"""
    parts: list[dict[str, object]] = []
    if text:
        parts.append({"type": "text", "text": text})
    for image in images:
        parts.append({"type": "image_url", "image_url": {"url": image.data_url()}})
    return parts


def build_chat_preview(
    *,
    context: DigestContext,
    messages: list[ChatMessage],
    period_metrics: PeriodMetricsPayload | None = None,
    event_time_buckets: EventTimeBucketsPayload | None = None,
    incident_timeline: IncidentTimelinePayload | None = None,
    extra_vcenter_strings: Sequence[str] | None = None,
    settings: Settings | None = None,
    attachments: Sequence[ChatAttachment] | None = None,
) -> tuple[str, list[ChatMessage], ChatLlmContextMeta | None]:
    """
    LLM API を呼び出さずに、送出するコンテキストブロックと会話履歴を準備する。

    添付がある場合はコンテキストブロックの末尾に添付ブロックを続けて返す
    （実際の送出でも同じ内容が直後の user メッセージになる）。

    Returns:
        (context_block_string, trimmed_messages, llm_context_meta)
    """
    s = settings or require_settings()
    ctx = build_chat_llm_context(
        context,
        messages,
        period_metrics,
        event_time_buckets,
        incident_timeline,
        extra_vcenter_strings,
        settings=s,
        attachments=attachments,
        supports_images=chat_provider_supports_images(s),
    )
    block = ctx.block
    if ctx.attachment_block:
        block = f"{block}\n\n{ctx.attachment_block}"
    return block, ctx.trimmed, ctx.meta


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
    web_search_scope: WebSearchScope = DEFAULT_WEB_SEARCH_SCOPE,
    web_search_aggressiveness: WebSearchAggressiveness = DEFAULT_WEB_SEARCH_AGGRESSIVENESS,
    attachments: Sequence[ChatAttachment] | None = None,
) -> tuple[str, str | None, ChatLlmContextMeta | None, int | None, float | None]:
    """
    集約 JSON と会話履歴を渡して LLM の応答本文を返す。

    ``period_metrics`` / ``event_time_buckets`` を渡すと ``digest_context`` とマージした JSON を入力とする。
    チャットでは ``digest_context`` からホスト別 CPU/メモリピーク（``high_cpu_hosts`` / ``high_mem_hosts``）を除く。

    ``runnable_config`` は将来 LangSmith 等の callbacks を渡すための拡張点（未使用でもよい）。

    ``extra_vcenter_strings`` に DB 登録済み vCenter の表示名・接続 host 等を渡すと、
    匿名化有効時に会話本文からもトークン化する（API ルートでは全件読込を渡す）。

    ``attachments`` はこの送信ターン限りの添付。テキストは匿名化のうえ専用ブロックとして、
    画像は最後の user メッセージのマルチモーダル content として渡す（保存はしない）。

    Returns:
        (assistant_text, error_message, llm_context_meta, latency_ms, token_per_sec)。
        チャット LLM が未設定のとき（``is_chat_llm_configured`` が False）は ("", None, None, None, None)。
        LLM 呼び出し前までに確定する統計は、HTTP 失敗時も第 3 要素に返す。
    """
    s = settings or require_settings()
    if not is_chat_llm_configured(s):
        return ("", None, None, None, None)

    ctx = build_chat_llm_context(
        context,
        messages,
        period_metrics,
        event_time_buckets,
        incident_timeline,
        extra_vcenter_strings,
        settings=s,
        attachments=attachments,
        supports_images=chat_provider_supports_images(s),
    )
    block = ctx.block
    trimmed = ctx.trimmed
    meta = ctx.meta
    reverse_map = ctx.reverse_map

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
            enable_web_search=web_search_provider is not None,
            scope=web_search_scope,
            aggressiveness=web_search_aggressiveness,
        )
        web_sources: list[WebSearchResult] = []
        # Copilot CLI は単一プロンプト文字列なので添付ブロックを連結して渡す
        copilot_block = (
            f"{block}\n\n{ctx.attachment_block}" if ctx.attachment_block else block
        )
        if cprof.provider == "copilot_cli" and not s.mock_mode:
            start_time = time.perf_counter()
            if web_search_provider is not None:
                text, web_sources = await run_copilot_chat_with_web_search(
                    s,
                    system_prompt=system_prompt,
                    block=copilot_block,
                    messages=trimmed,
                    provider=web_search_provider,
                    scope=web_search_scope,
                )
            else:
                text = await run_copilot_cli_chat_completion(
                    s,
                    system_prompt=system_prompt,
                    block=copilot_block,
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
                block,
                trimmed,
                system_prompt=system_prompt,
                attachment_block=ctx.attachment_block,
                images=ctx.images,
            )
            if web_search_provider is not None:
                start_time = time.perf_counter()
                text, web_sources = await run_chat_with_web_search(
                    model,
                    lc_messages,
                    web_search_provider,
                    s,
                    scope=web_search_scope,
                    config=runnable_config,
                )
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                token_per_sec = None
            else:
                text, latency_ms, token_per_sec = await stream_chat_to_text(
                    model, lc_messages, config=runnable_config
                )
        text = deanonymize_text(text.strip(), reverse_map)
        if meta.attachments_dropped_reason:
            text = f"（{meta.attachments_dropped_reason}）\n\n{text}"
        # 出典は実際のツール実行結果からサーバ側で連結（LLM 出力の URL は一次情報にしない）
        sources_block = render_web_search_sources(web_sources)
        if sources_block:
            text = text.rstrip() + "\n\n" + sources_block
        return (text, None, meta, latency_ms, token_per_sec)
    except Exception as e:
        log_llm_failure(s, "chat", e)
        detail = _llm_failure_detail_for_user(e)
        return ("", f"チャット応答を取得できませんでした（{detail}）", meta, None, None)
