"""期間集約コンテキストを用いたチャット用 LLM 呼び出し（OpenAI 互換または Google Gemini REST）。"""

from __future__ import annotations

import logging
from typing import Any

import httpx

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
_MAX_CHAT_MESSAGE_CHARS_TOTAL = 32_000

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


def _trim_chat_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    """件数・合計文字数の上限で古いターンから削る。"""
    trimmed = messages[-_MAX_CHAT_MESSAGES:]
    while trimmed:
        total = sum(len(m.content) for m in trimmed)
        if total <= _MAX_CHAT_MESSAGE_CHARS_TOTAL:
            break
        trimmed = trimmed[1:]
    return trimmed


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

    trimmed = _trim_chat_messages(messages)
    ctx_json = _trim_context_json(context.model_dump(mode="json"))
    block = _context_user_block(ctx_json)

    api_messages: list[dict[str, str]] = [
        {"role": "system", "content": _CHAT_SYSTEM_PROMPT},
        {"role": "user", "content": block},
    ]
    for m in trimmed:
        api_messages.append({"role": m.role, "content": m.content})

    try:
        _logger.info(
            "chat LLM リクエスト json_chars=%s message_turns=%s timeout_seconds=%s model=%s",
            len(ctx_json),
            len(trimmed),
            settings.llm_timeout_seconds,
            settings.llm_model,
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
