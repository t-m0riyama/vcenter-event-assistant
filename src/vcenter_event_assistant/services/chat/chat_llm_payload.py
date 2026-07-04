"""チャット LLM 向け payload 構築とトークン予算調整（LLM 呼び出し非依存）。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from functools import lru_cache
from typing import Any

import tiktoken

from vcenter_event_assistant.api.schemas import ChatLlmContextMeta, ChatMessage
from vcenter_event_assistant.services.chat.chat_event_time_buckets import EventTimeBucketsPayload
from vcenter_event_assistant.services.chat.chat_incident_timeline import IncidentTimelinePayload
from vcenter_event_assistant.services.chat.chat_period_metrics import PeriodMetricsPayload
from vcenter_event_assistant.services.digest.digest_context import DigestContext
from vcenter_event_assistant.services.digest.digest_llm import _trim_context_json
from vcenter_event_assistant.services.llm.llm_anonymization import anonymize_chat_for_llm
from vcenter_event_assistant.settings import Settings
from vcenter_event_assistant.settings_binding import require_settings

MAX_CHAT_MESSAGES = 20

# digest_llm._trim_context_json の切り詰め末尾と同一（二分探索で使用）
_JSON_TRUNCATION_SUFFIX = "\n…（JSON 長のため切り詰め）"

# メッセージ境界のオーバーヘッド（tiktoken 推定に加算する概算。OpenAI / Gemini いずれも厳密ではない）
_CHAT_MESSAGE_OVERHEAD_TOKENS_PER_TURN = 4

CHAT_SYSTEM_PROMPT = (
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
    "- 日本語で簡潔に答える。不要に長い Markdown やコードフェンスは避ける。"
    " ユーザーが出力形式（見出し・箇条書き・セクション構成）を明示した場合はその形式に従う。"
    " その場合でも事実・数値は JSON に根ざし、コードフェンスは使わない。\n"
    "- ホスト名・イベント種別・件数などを引用するときは、JSON の値と矛盾させない。\n"
    "- 応答に `__LM_` で始まる内部識別子（匿名化用プレースホルダ）を出力しない。"
    " 入力 JSON や会話に現れるホスト名等は、その表記をそのまま引用する。\n"
    "- ホスト名や識別子に括弧で別名・補足を付けて二重に表現しない（同一ホストを短縮名と FQDN で対照しない）。\n"
)


@lru_cache(maxsize=1)
def _chat_token_encoding() -> tiktoken.Encoding:
    """チャット入力のトークン目安（Gemini 公式のトークン数と一致しない場合がある）。"""
    return tiktoken.get_encoding("cl100k_base")


def _trim_json_raw(raw: str, max_chars: int) -> str:
    """単一の JSON 文字列を切り詰める（`json.dumps` は呼び出し側で1回にまとめる）。"""
    if len(raw) <= max_chars:
        return raw
    return raw[:max_chars] + _JSON_TRUNCATION_SUFFIX


def estimate_chat_input_tokens(block: str, trimmed: list[ChatMessage]) -> int:
    """
    システムプロンプト + コンテキストブロック + 会話のトークン数の目安。

    OpenAI 互換・Gemini ともに同一の文字列集合を想定した近似（Gemini 公式とは一致しない）。
    """
    enc = _chat_token_encoding()
    n = len(enc.encode(CHAT_SYSTEM_PROMPT)) + len(enc.encode(block))
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
    block = merged_context_user_block(full)
    if estimate_chat_input_tokens(block, trimmed) <= max_tokens:
        return full, False

    lo, hi = 1, max(1, len(full) - 1)
    best: str | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        ctx = _trim_json_raw(full, mid)
        blk = merged_context_user_block(ctx)
        if estimate_chat_input_tokens(blk, trimmed) <= max_tokens:
            best = ctx
            lo = mid + 1
        else:
            hi = mid - 1

    if best is None:
        return _trim_json_raw(full, 1), True
    return best, True


def fit_chat_payload_to_token_budget(
    payload: dict[str, Any],
    messages: list[ChatMessage],
    *,
    settings: Settings | None = None,
) -> tuple[str, list[ChatMessage], bool]:
    """
    集約 JSON と会話を `llm_chat_max_input_tokens` 以下に収める。

    先に JSON を短くし、足りなければ古い会話から削る。

    Returns:
        (ctx_json, trimmed_messages, json_truncated)
    """
    settings = settings or require_settings()
    max_tokens = settings.llm_chat_max_input_tokens
    trimmed = messages[-MAX_CHAT_MESSAGES:]
    json_truncated = False

    while True:
        raw_json = json.dumps(payload, ensure_ascii=False)
        ctx_json, jtrunc = _best_json_string_for_budget(raw_json, trimmed, max_tokens)
        json_truncated = json_truncated or jtrunc
        block = merged_context_user_block(ctx_json)
        if estimate_chat_input_tokens(block, trimmed) <= max_tokens:
            return ctx_json, trimmed, json_truncated
        if not trimmed:
            ctx_json = _trim_context_json(payload, max_chars=1)
            return ctx_json, [], True
        trimmed = trimmed[1:]


def merged_context_user_block(ctx_json: str) -> str:
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


def prepare_chat_payload(
    context: DigestContext,
    messages: list[ChatMessage],
    period_metrics: PeriodMetricsPayload | None,
    event_time_buckets: EventTimeBucketsPayload | None,
    incident_timeline: IncidentTimelinePayload | None,
    extra_vcenter_strings: Sequence[str] | None,
    *,
    settings: Settings | None = None,
) -> tuple[dict[str, Any], list[ChatMessage], dict[str, str]]:
    """digest_context から high_cpu/mem を除外 → payload 構築 → 匿名化。

    Returns:
        (payload, trimmed_messages, reverse_map)
    """
    settings = settings or require_settings()
    digest_obj = context.model_dump(mode="json")
    digest_obj.pop("high_cpu_hosts", None)
    digest_obj.pop("high_mem_hosts", None)
    payload: dict[str, Any] = {"digest_context": digest_obj}
    if period_metrics is not None:
        payload["period_metrics"] = period_metrics.model_dump(mode="json")
    if event_time_buckets is not None:
        payload["event_time_buckets"] = event_time_buckets.model_dump(mode="json")
    if incident_timeline is not None:
        payload["incident_timeline"] = incident_timeline.model_dump(mode="json")

    trimmed_msgs = messages[-MAX_CHAT_MESSAGES:]
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


def build_chat_llm_context(
    context: DigestContext,
    messages: list[ChatMessage],
    period_metrics: PeriodMetricsPayload | None,
    event_time_buckets: EventTimeBucketsPayload | None,
    incident_timeline: IncidentTimelinePayload | None,
    extra_vcenter_strings: Sequence[str] | None,
    *,
    settings: Settings | None = None,
) -> tuple[str, list[ChatMessage], ChatLlmContextMeta, dict[str, str]]:
    """LLM 呼び出し前のコンテキストブロック・会話・メタデータを構築する。"""
    settings = settings or require_settings()
    payload, trimmed_msgs, reverse_map = prepare_chat_payload(
        context,
        messages,
        period_metrics,
        event_time_buckets,
        incident_timeline,
        extra_vcenter_strings,
        settings=settings,
    )
    ctx_json, trimmed, json_truncated = fit_chat_payload_to_token_budget(
        payload,
        trimmed_msgs,
        settings=settings,
    )
    block = merged_context_user_block(ctx_json)
    est_tokens = estimate_chat_input_tokens(block, trimmed)
    meta = ChatLlmContextMeta(
        json_truncated=json_truncated,
        estimated_input_tokens=est_tokens,
        max_input_tokens=settings.llm_chat_max_input_tokens,
        message_turns=len(trimmed),
    )
    return block, trimmed, meta, reverse_map
