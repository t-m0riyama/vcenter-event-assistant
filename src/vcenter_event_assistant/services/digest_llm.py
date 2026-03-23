"""ダイジェスト用 LLM 呼び出し（OpenAI 互換または Google Gemini REST）。"""

from __future__ import annotations

import json
from typing import Any

import httpx

from vcenter_event_assistant.services.digest_context import DigestContext
from vcenter_event_assistant.settings import Settings

_MAX_CONTEXT_JSON_CHARS = 80_000

_SYSTEM_PROMPT = (
    "あなたは vCenter 運用のアシスタントです。与えられた集約 JSON とテンプレート Markdown を踏まえ、"
    "運用者向けの短い要約のみを出力してください。出力は必ず Markdown で、"
    "先頭行を「## LLM 要約」とし、その下に日本語の箇条書きを続けてください。"
    "数値・事実は入力を正とし、推測で情報を追加しないでください。"
)


def _trim_context_json(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False)
    if len(raw) <= _MAX_CONTEXT_JSON_CHARS:
        return raw
    return raw[:_MAX_CONTEXT_JSON_CHARS] + "\n…（JSON 長のため切り詰め）"


async def augment_digest_with_llm(
    settings: Settings,
    *,
    context: DigestContext,
    template_markdown: str,
) -> tuple[str, str | None]:
    """
    テンプレートに LLM 要約を追記した本文を返す。

    Returns:
        (body_markdown, error_message)。API キーが空のときは (template_markdown, None)。
        LLM 失敗時は (template_markdown, 警告文)。
    """
    key = (settings.llm_api_key or "").strip()
    if not key:
        return (template_markdown, None)

    ctx_json = _trim_context_json(context.model_dump(mode="json"))
    user_block = f"集約 JSON:\n```json\n{ctx_json}\n```\n\n---\nテンプレート:\n{template_markdown}"

    try:
        timeout = httpx.Timeout(settings.llm_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            if settings.llm_provider == "openai_compatible":
                summary = await _openai_chat_completion(client, settings, key, user_block)
            else:
                summary = await _gemini_generate_content(client, settings, key, user_block)
        merged = template_markdown.rstrip() + "\n\n" + summary.strip() + "\n"
        return (merged, None)
    except Exception as e:
        return (template_markdown, f"LLM 要約は省略（{e!s}）")


async def _openai_chat_completion(
    client: httpx.AsyncClient,
    settings: Settings,
    api_key: str,
    user_block: str,
) -> str:
    base = settings.llm_base_url.rstrip("/")
    url = f"{base}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_block},
        ],
    }
    r = await client.post(url, headers=headers, json=body)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:2000]}")
    data = r.json()
    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as e:
        raise ValueError(f"OpenAI 互換レスポンスの解析に失敗: {data!r}") from e


async def _gemini_generate_content(
    client: httpx.AsyncClient,
    settings: Settings,
    api_key: str,
    user_block: str,
) -> str:
    model = settings.llm_model.strip()
    # クエリ ?key= は httpx の INFO ログに URL ごと出るため、x-goog-api-key ヘッダーで送る。
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{model}:generateContent"
    )
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    body: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_block}]}],
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
