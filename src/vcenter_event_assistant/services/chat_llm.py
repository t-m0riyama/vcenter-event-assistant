"""期間集約コンテキストを用いたチャット用 LLM 呼び出し（LangChain: OpenAI 互換または Gemini）。"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Sequence
from functools import lru_cache
from typing import Any

import tiktoken
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from vcenter_event_assistant.api.schemas import ChatLlmContextMeta, ChatMessage
from vcenter_event_assistant.services.chat_event_time_buckets import EventTimeBucketsPayload
from vcenter_event_assistant.services.chat_period_metrics import PeriodMetricsPayload
from vcenter_event_assistant.services.digest_context import DigestContext
from vcenter_event_assistant.services.digest_llm import _trim_context_json
from vcenter_event_assistant.services.llm_anonymization import anonymize_chat_for_llm, deanonymize_text
from vcenter_event_assistant.services.llm_user_errors import _llm_failure_detail_for_user
from vcenter_event_assistant.services.copilot_cli_llm import run_copilot_cli_chat_completion
from vcenter_event_assistant.services.llm_factory import build_chat_model
from vcenter_event_assistant.services.llm_profile import (
    is_chat_llm_configured,
    resolve_llm_profile,
)
from vcenter_event_assistant.services.llm_invoke import stream_chat_to_text
from vcenter_event_assistant.settings import Settings

_logger = logging.getLogger(__name__)

_MAX_CHAT_MESSAGES = 20

# digest_llm._trim_context_json の切り詰め末尾と同一（二分探索で使用）
_JSON_TRUNCATION_SUFFIX = "\n…（JSON 長のため切り詰め）"

# メッセージ境界のオーバーヘッド（tiktoken 推定に加算する概算。OpenAI / Gemini いずれも厳密ではない）
_CHAT_MESSAGE_OVERHEAD_TOKENS_PER_TURN = 4


@lru_cache(maxsize=1)
def _chat_token_encoding() -> tiktoken.Encoding:
    """チャット入力のトークン目安（Gemini 公式のトークン数と一致しない場合がある）。"""
    return tiktoken.get_encoding("cl100k_base")

_CHAT_SYSTEM_PROMPT = (
    "あなたは vCenter 運用のアシスタントです。入力 JSON の構造を次のように解釈してください。\n"
    "\n"
    "【digest_context】"
    " 集計期間は from_utc〜to_utc（他ブロックと同じ）。"
    " top_notable_event_groups には種別ごとに occurred_at_first / occurred_at_last などの時刻フィールドがある"
    "（全件の発生時刻リストではないが、時刻情報が無いと誤解しないこと）。"
    " top_event_types は種別ごとの件数サマリ。total_events は期間内の合計です。\n"
    "\n"
    "【period_metrics】（キーがある場合のみ）"
    " 同じ期間のメトリクスをホスト等ごとに時間バケット平均したもの（利用者がオンにしたカテゴリのみ）。"
    " 値は常に「高負荷」を意味するわけではなく、通常範囲や一部指標だけの場合もある。"
    " bucket_start_utc はバケット開始時刻。digest_context のイベントとは別集計であり、"
    "イベント 1 件とメトリクス 1 点を同一レコードで結合したデータではない。\n"
    "\n"
    "【event_time_buckets】（キーがある場合のみ）"
    " 同じ期間のイベントを、period_metrics と同一の bucket 幅（bucket_minutes / bucket_start_utc の刻み）で"
    " 件数集計したもの。digest の top_notable 等とは別クエリ。行単位でメトリクスと結合したデータではないが、"
    " 時刻軸は揃っているため粗い対照として言及できる。\n"
    "\n"
    "【相関について】"
    " メトリクスとイベントを時刻で 1 対 1 に結びつけ、「負荷の瞬間にどのイベントが起きたか」を厳密に証明する情報は通常含まれない。"
    " period_metrics の値は高負荷を前提としない。ただし occurred_at_* や event_time_buckets と"
    " 同一期間・同一バケット刻みで粗く並べて対照として言及することはできる。"
    " 近接や傾向から因果を断定しない。\n"
    "\n"
    "【回答の原則】\n"
    "- 事実・数値は、与えられた JSON（および会話内で明示された内容）に根ざして答える。推測で新しい事実を加えない。\n"
    "- JSON に無い情報は「不明」「入力に含まれていません」と述べる。\n"
    "- top_notable_event_groups に時刻フィールドがあるのに「イベントに時刻がない」と述べない。\n"
    "- 日本語で簡潔に答える。不要に長い Markdown やコードフェンスは避ける。\n"
    "- ホスト名・イベント種別・件数などを引用するときは、JSON の値と矛盾させない。\n"
    "- 応答に `__LM_` で始まる内部識別子（匿名化用プレースホルダ）を出力しない。"
    " 入力 JSON や会話に現れるホスト名等は、その表記をそのまま引用する。\n"
    "- ホスト名や識別子に括弧で別名・補足を付けて二重に表現しない（同一ホストを短縮名と FQDN で対照しない）。\n"
)


def _log_chat_llm_failure(settings: Settings, exc: BaseException) -> None:
    """運用向け。API キーはログに出さない。"""
    prof = resolve_llm_profile(settings, purpose="chat")
    if prof.provider == "openai_compatible":
        base = (prof.base_url or "").rstrip("/")
        _logger.warning(
            "chat LLM 呼び出しに失敗 provider=openai_compatible base_url=%s model=%s exc=%r",
            base,
            prof.model,
            exc,
            exc_info=True,
        )
    elif prof.provider == "copilot_cli":
        _logger.warning(
            "chat LLM 呼び出しに失敗 provider=copilot_cli model=%s exc=%r",
            prof.model,
            exc,
            exc_info=True,
        )
    else:
        _logger.warning(
            "chat LLM 呼び出しに失敗 provider=gemini model=%s exc=%r",
            prof.model,
            exc,
            exc_info=True,
        )


def _trim_json_raw(raw: str, max_chars: int) -> str:
    """単一の JSON 文字列を切り詰める（`json.dumps` は呼び出し側で1回にまとめる）。"""
    if len(raw) <= max_chars:
        return raw
    return raw[:max_chars] + _JSON_TRUNCATION_SUFFIX


def _estimate_chat_input_tokens(block: str, trimmed: list[ChatMessage]) -> int:
    """
    システムプロンプト + コンテキストブロック + 会話のトークン数の目安。

    OpenAI 互換・Gemini ともに同一の文字列集合を想定した近似（Gemini 公式とは一致しない）。
    """
    enc = _chat_token_encoding()
    n = len(enc.encode(_CHAT_SYSTEM_PROMPT)) + len(enc.encode(block))
    for m in trimmed:
        n += len(enc.encode(m.content))
    n += _CHAT_MESSAGE_OVERHEAD_TOKENS_PER_TURN * (2 + len(trimmed))
    return n


def _best_json_string_for_budget(
    raw_json: str,
    trimmed: list[ChatMessage],
    max_tokens: int,
) -> tuple[str, bool]:
    """
    `raw_json` を短くしつつ、推定トークンが `max_tokens` 以下になるよう調整する。

    Returns:
        (ctx_json, truncated)。全文が収まるときは truncated=False。
    """
    full = raw_json
    block = _merged_context_user_block(full)
    if _estimate_chat_input_tokens(block, trimmed) <= max_tokens:
        return full, False

    lo, hi = 1, max(1, len(full) - 1)
    best: str | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        ctx = _trim_json_raw(full, mid)
        blk = _merged_context_user_block(ctx)
        if _estimate_chat_input_tokens(blk, trimmed) <= max_tokens:
            best = ctx
            lo = mid + 1
        else:
            hi = mid - 1

    if best is None:
        return _trim_json_raw(full, 1), True
    return best, True


def _fit_chat_payload_to_token_budget(
    settings: Settings,
    payload: dict[str, Any],
    messages: list[ChatMessage],
) -> tuple[str, list[ChatMessage], bool]:
    """
    集約 JSON と会話を `llm_chat_max_input_tokens` 以下に収める。

    先に JSON を短くし、足りなければ古い会話から削る。

    Returns:
        (ctx_json, trimmed_messages, json_truncated)
    """
    max_tokens = settings.llm_chat_max_input_tokens
    trimmed = messages[-_MAX_CHAT_MESSAGES:]
    json_truncated = False

    while True:
        raw_json = json.dumps(payload, ensure_ascii=False)
        ctx_json, jtrunc = _best_json_string_for_budget(raw_json, trimmed, max_tokens)
        json_truncated = json_truncated or jtrunc
        block = _merged_context_user_block(ctx_json)
        if _estimate_chat_input_tokens(block, trimmed) <= max_tokens:
            return ctx_json, trimmed, json_truncated
        if not trimmed:
            ctx_json = _trim_context_json(payload, max_chars=1)
            return ctx_json, [], True
        trimmed = trimmed[1:]


def _merged_context_user_block(ctx_json: str) -> str:
    """マージ済み JSON（`digest_context` ± `period_metrics` ± `event_time_buckets`）のユーザーブロック。"""
    return (
        "以下は同一指定期間の vCenter 集約 JSON です。"
        " `digest_context` はイベントの件数・種別サマリと、要注意グループ（occurred_at_first / occurred_at_last 等を含む）。"
        " チャットではホスト別 CPU/メモリのピーク一覧は省いています。"
        " `period_metrics` がある場合はメトリクスのバケット平均（digest と別クエリ。行単位の結合ではない。"
        " 値は常に高負荷を意味するわけではない）。"
        " `event_time_buckets` がある場合はイベント件数の時間バケット（period_metrics と同一時刻軸だが行単位結合ではない）。"
        " システムプロンプトの【digest_context】【period_metrics】【event_time_buckets】の説明に従って解釈してください。\n\n"
        f"```json\n{ctx_json}\n```"
    )


def _to_langchain_messages(block: str, trimmed: list[ChatMessage]) -> list[BaseMessage]:
    """システム・コンテキスト JSON ブロック・会話履歴を LangChain メッセージ列に変換する。"""
    out: list[BaseMessage] = [
        SystemMessage(content=_CHAT_SYSTEM_PROMPT),
        HumanMessage(content=block),
    ]
    for m in trimmed:
        if m.role == "user":
            out.append(HumanMessage(content=m.content))
        else:
            out.append(AIMessage(content=m.content))
    return out
def _prepare_chat_payload(
    settings: Settings,
    context: DigestContext,
    messages: list[ChatMessage],
    period_metrics: PeriodMetricsPayload | None,
    event_time_buckets: EventTimeBucketsPayload | None,
    extra_vcenter_strings: Sequence[str] | None,
) -> tuple[dict[str, Any], list[ChatMessage], dict[str, str]]:
    """digest_context から high_cpu/mem を除外 → payload 構築 → 匿名化。

    Returns:
        (payload, trimmed_messages, reverse_map)
    """
    digest_obj = context.model_dump(mode="json")
    digest_obj.pop("high_cpu_hosts", None)
    digest_obj.pop("high_mem_hosts", None)
    payload: dict[str, Any] = {"digest_context": digest_obj}
    if period_metrics is not None:
        payload["period_metrics"] = period_metrics.model_dump(mode="json")
    if event_time_buckets is not None:
        payload["event_time_buckets"] = event_time_buckets.model_dump(mode="json")

    trimmed_msgs = messages[-_MAX_CHAT_MESSAGES:]
    reverse_map: dict[str, str] = {}
    if settings.llm_anonymization_enabled:
        pl, contents, reverse_map = anonymize_chat_for_llm(
            payload,
            [m.content for m in trimmed_msgs],
            extra_vcenter_strings=extra_vcenter_strings,
        )
        payload = pl
        trimmed_msgs = [
            ChatMessage(role=m.role, content=c) for m, c in zip(trimmed_msgs, contents, strict=True)
        ]

    return payload, trimmed_msgs, reverse_map


def build_chat_preview(
    settings: Settings,
    *,
    context: DigestContext,
    messages: list[ChatMessage],
    period_metrics: PeriodMetricsPayload | None = None,
    event_time_buckets: EventTimeBucketsPayload | None = None,
    extra_vcenter_strings: Sequence[str] | None = None,
) -> tuple[str, list[ChatMessage], ChatLlmContextMeta | None]:
    """
    LLM API を呼び出さずに、送出するコンテキストブロックと会話履歴を準備する。
    Returns:
        (context_block_string, trimmed_messages, llm_context_meta)
    """
    payload, trimmed_msgs, _ = _prepare_chat_payload(
        settings, context, messages,
        period_metrics, event_time_buckets, extra_vcenter_strings,
    )

    ctx_json, trimmed, json_truncated = _fit_chat_payload_to_token_budget(settings, payload, trimmed_msgs)
    block = _merged_context_user_block(ctx_json)
    est_tokens = _estimate_chat_input_tokens(block, trimmed)
    meta = ChatLlmContextMeta(
        json_truncated=json_truncated,
        estimated_input_tokens=est_tokens,
        max_input_tokens=settings.llm_chat_max_input_tokens,
        message_turns=len(trimmed),
    )
    return block, trimmed, meta


async def run_period_chat(
    settings: Settings,
    *,
    context: DigestContext,
    messages: list[ChatMessage],
    period_metrics: PeriodMetricsPayload | None = None,
    event_time_buckets: EventTimeBucketsPayload | None = None,
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
        チャット LLM が未設定のとき（``is_chat_llm_configured`` が False）は (\"\", None, None, None, None)。
        LLM 呼び出し前までに確定する統計は、HTTP 失敗時も第 3 要素に返す。
    """
    if not is_chat_llm_configured(settings):
        return ("", None, None, None, None)

    payload, trimmed_msgs, reverse_map = _prepare_chat_payload(
        settings, context, messages,
        period_metrics, event_time_buckets, extra_vcenter_strings,
    )

    ctx_json, trimmed, json_truncated = _fit_chat_payload_to_token_budget(settings, payload, trimmed_msgs)
    block = _merged_context_user_block(ctx_json)
    est_tokens = _estimate_chat_input_tokens(block, trimmed)
    meta = ChatLlmContextMeta(
        json_truncated=json_truncated,
        estimated_input_tokens=est_tokens,
        max_input_tokens=settings.llm_chat_max_input_tokens,
        message_turns=len(trimmed),
    )

    try:
        cprof = resolve_llm_profile(settings, purpose="chat")
        _logger.info(
            "chat LLM リクエスト est_input_tokens=%s json_chars=%s json_truncated=%s message_turns=%s "
            "timeout_seconds=%s model=%s max_input_tokens=%s",
            est_tokens,
            len(ctx_json),
            json_truncated,
            len(trimmed),
            cprof.timeout_seconds,
            cprof.model,
            settings.llm_chat_max_input_tokens,
        )
        if cprof.provider == "copilot_cli":
            start_time = time.perf_counter()
            text = await run_copilot_cli_chat_completion(
                settings,
                system_prompt=_CHAT_SYSTEM_PROMPT,
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
        _log_chat_llm_failure(settings, e)
        detail = _llm_failure_detail_for_user(e)
        return ("", f"チャット応答を取得できませんでした（{detail}）", meta, None, None)
