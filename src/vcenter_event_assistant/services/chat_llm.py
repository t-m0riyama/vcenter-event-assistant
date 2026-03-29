"""期間集約コンテキストを用いたチャット用 LLM 呼び出し（OpenAI 互換または Google Gemini REST）。"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

import httpx
import tiktoken

from vcenter_event_assistant.api.schemas import ChatMessage
from vcenter_event_assistant.services.digest_context import DigestContext
from vcenter_event_assistant.services.digest_llm import (
    _collect_openai_chat_stream_text,
    _llm_failure_detail_for_user,
    _trim_context_json,
)
from vcenter_event_assistant.settings import Settings

_logger = logging.getLogger(__name__)

_MAX_CHAT_MESSAGES = 20

# digest_llm._trim_context_json の切り詰め末尾と同一（二分探索で使用）
_JSON_TRUNCATION_SUFFIX = "\n…（JSON 長のため切り詰め）"

# メッセージ境界のオーバーヘッド（tiktoken 推定に加算する概算。OpenAI / Gemini いずれも厳密ではない）
_CHAT_MESSAGE_OVERHEAD_TOKENS_PER_TURN = 4


@lru_cache(maxsize=1)
def _chat_token_encoding() -> tiktoken.Encoding:
    """チャット入力のトークン目安（Gemini 公式のカウントとは一致しない場合がある）。"""
    return tiktoken.get_encoding("cl100k_base")

_CHAT_SYSTEM_PROMPT = (
    "あなたは vCenter 運用のアシスタントです。入力には、指定期間に集約したイベントとメトリクスの JSON と、"
    "運用者との会話履歴が含まれます。\n"
    "\n"
    "【回答の原則】\n"
    "- 事実・数値は、与えられた JSON（および会話内で明示された内容）に根ざして答える。推測で新しい事実を加えない。\n"
    "- JSON に無い情報は「不明」「入力に含まれていません」と述べる。\n"
    "- 日本語で簡潔に答える。不要に長い Markdown やコードフェンスは避ける。\n"
    "- ホスト名・イベント種別・件数などを引用するときは、JSON の値と矛盾させない。\n"
)


def _log_chat_llm_failure(settings: Settings, exc: BaseException) -> None:
    """運用向け。API キーはログに出さない。"""
    if settings.llm_provider == "openai_compatible":
        base = (settings.llm_base_url or "").rstrip("/")
        _logger.warning(
            "chat LLM 呼び出しに失敗 provider=openai_compatible base_url=%s model=%s exc=%r",
            base,
            settings.llm_model,
            exc,
            exc_info=True,
        )
    else:
        _logger.warning(
            "chat LLM 呼び出しに失敗 provider=gemini model=%s exc=%r",
            settings.llm_model,
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
    block = _context_user_block(full)
    if _estimate_chat_input_tokens(block, trimmed) <= max_tokens:
        return full, False

    lo, hi = 1, max(1, len(full) - 1)
    best: str | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        ctx = _trim_json_raw(full, mid)
        blk = _context_user_block(ctx)
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
        block = _context_user_block(ctx_json)
        if _estimate_chat_input_tokens(block, trimmed) <= max_tokens:
            return ctx_json, trimmed, json_truncated
        if not trimmed:
            ctx_json = _trim_context_json(payload, max_chars=1)
            return ctx_json, [], True
        trimmed = trimmed[1:]


def _context_user_block(ctx_json: str) -> str:
    return (
        "以下は指定期間の vCenter イベント・メトリクス集約 JSON です。"
        "これを根拠として後続の会話に答えてください。\n\n"
        f"```json\n{ctx_json}\n```"
    )


async def _openai_chat_with_messages(
    client: httpx.AsyncClient,
    settings: Settings,
    api_key: str,
    messages: list[dict[str, str]],
) -> str:
    base = settings.llm_base_url.rstrip("/")
    url = f"{base}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": messages,
        "stream": True,
    }
    async with client.stream("POST", url, headers=headers, json=body) as response:
        if response.status_code >= 400:
            err_body = (await response.aread()).decode("utf-8", errors="replace")[:2000]
            raise RuntimeError(f"HTTP {response.status_code}: {err_body}")
        text = await _collect_openai_chat_stream_text(response)
    if not text.strip():
        raise ValueError("OpenAI 互換ストリーミング応答に assistant 本文がありません（choices[].delta.content が空）")
    return text


async def _gemini_chat_generate(
    client: httpx.AsyncClient,
    settings: Settings,
    api_key: str,
    context_block: str,
    messages: list[ChatMessage],
) -> str:
    model = settings.llm_model.strip()
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{model}:generateContent"
    )
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    contents: list[dict[str, Any]] = [
        {"role": "user", "parts": [{"text": context_block}]},
    ]
    for m in messages:
        grole = "user" if m.role == "user" else "model"
        contents.append({"role": grole, "parts": [{"text": m.content}]})
    body: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": _CHAT_SYSTEM_PROMPT}]},
        "contents": contents,
    }
    r = await client.post(url, headers=headers, json=body)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:2000]}")
    data = r.json()
    try:
        cands = data.get("candidates") or []
        if not cands:
            raise ValueError(f"Gemini candidates が空: {data!r}")
        parts = cands[0].get("content", {}).get("parts") or []
        if not parts:
            raise ValueError(f"Gemini parts が空: {data!r}")
        return str(parts[0]["text"])
    except (KeyError, IndexError, TypeError) as e:
        raise ValueError(f"Gemini レスポンスの解析に失敗: {data!r}") from e


async def run_period_chat(
    settings: Settings,
    *,
    context: DigestContext,
    messages: list[ChatMessage],
) -> tuple[str, str | None]:
    """
    集約 JSON と会話履歴を渡して LLM の応答本文を返す。

    Returns:
        (assistant_text, error_message)。API キーが空のときは (\"\", None)。
        LLM 失敗時は (\"\", ユーザー向け短文)。
    """
    key = (settings.llm_api_key or "").strip()
    if not key:
        return ("", None)

    payload = context.model_dump(mode="json")
    ctx_json, trimmed, json_truncated = _fit_chat_payload_to_token_budget(settings, payload, messages)
    block = _context_user_block(ctx_json)
    est_tokens = _estimate_chat_input_tokens(block, trimmed)

    api_messages: list[dict[str, str]] = [
        {"role": "system", "content": _CHAT_SYSTEM_PROMPT},
        {"role": "user", "content": block},
    ]
    for m in trimmed:
        api_messages.append({"role": m.role, "content": m.content})

    try:
        _logger.info(
            "chat LLM リクエスト est_input_tokens=%s json_chars=%s json_truncated=%s message_turns=%s "
            "timeout_seconds=%s model=%s max_input_tokens=%s",
            est_tokens,
            len(ctx_json),
            json_truncated,
            len(trimmed),
            settings.llm_timeout_seconds,
            settings.llm_model,
            settings.llm_chat_max_input_tokens,
        )
        timeout = httpx.Timeout(settings.llm_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            if settings.llm_provider == "openai_compatible":
                text = await _openai_chat_with_messages(client, settings, key, api_messages)
            else:
                text = await _gemini_chat_generate(client, settings, key, block, trimmed)
        return (text.strip(), None)
    except Exception as e:
        _log_chat_llm_failure(settings, e)
        detail = _llm_failure_detail_for_user(e)
        return ("", f"チャット応答を取得できませんでした（{detail}）")
