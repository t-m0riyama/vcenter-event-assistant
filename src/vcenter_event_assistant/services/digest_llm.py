"""ダイジェスト用 LLM 呼び出し（OpenAI 互換または Google Gemini REST）。"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from vcenter_event_assistant.services.digest_context import DigestContext
from vcenter_event_assistant.settings import Settings

_logger = logging.getLogger(__name__)

_MAX_CONTEXT_JSON_CHARS = 80_000

_SYSTEM_PROMPT = (
    "あなたは vCenter 運用のアシスタントです。入力には集約 JSON と、運用者向けに既に整形された"
    "ダイジェスト Markdown（テンプレート）が含まれます。\n"
    "あなたの出力は、その本文の末尾に追記される「## LLM 要約」ブロックだけです。\n"
    "\n"
    "【出力形式】\n"
    "- 先頭行を必ず「## LLM 要約」とし、その下に日本語の箇条書き（3〜8 項目程度）のみ。\n"
    "- このブロック以外（別見出し・説明文・コードフェンス）は出力しない。\n"
    "\n"
    "【禁止：本文との重複】\n"
    "次に該当する内容は、言い換え・略称・並べ替えを含め書かないこと。\n"
    "- ダイジェスト先頭のタイトル（日次/週次/月次など）の言い換え。\n"
    "- 集計期間、登録 vCenter 数、イベント総数、要注意（notable_score ≥ 40）件数の列挙・再掲。\n"
    "- 「上位イベント種別」「要注意イベント」「ホスト CPU/メモリ利用率」など、本文に表・箇条書きで"
    "既に示されている数値・順位・ホスト名・イベント種別を、箇条書きでなぞって書くこと"
    "（件数の羅列、上位の転記、表の言い換えのみ）。\n"
    "\n"
    "【推奨：補足として書くこと】\n"
    "入力に根拠がある範囲で、本文だけでは伝わりにくい運用上の手がかりに絞ること。例：\n"
    "- 要注意件数が 0 でも、閾値未満のスコアで「要注意イベント」に現れている事象があれば、"
    "その確認の優先度（入力の event_type・message 等を引用してよい）。\n"
    "- イベント種別の大半が特定カテゴリに偏っている場合、その読み方"
    "（数値の再掲ではなく、他セクションをどう見るか）。\n"
    "- メトリクス表とイベント一覧を横断して見るべきか、入力から言える範囲での示唆。\n"
    "\n"
    "【忠実性】\n"
    "数値・事実は入力（JSON および本文に書かれた内容）を正とし、推測で情報を追加しない。"
    "不明なことは書かない。"
)


def _llm_failure_detail_for_user(exc: BaseException) -> str:
    """
    ユーザー向け `error_message` 用。

    - httpx のタイムアウトは `ReadTimeout('')` のように `str` が空になりやすいため、
      日本語で「応答がタイムアウト」と明示する。
    - その他で `str(exc)` が空や空白のみのときは例外型名を返す（「省略（）」を防ぐ）。
    """
    if isinstance(exc, httpx.TimeoutException):
        text = str(exc).strip()
        head = type(exc).__name__ + (f": {text}" if text else "")
        return (
            f"{head}（応答がタイムアウトしました。LLM_TIMEOUT_SECONDS を延長するか、"
            "ローカル Ollama ではより軽いモデル・短いプロンプトを検討してください）"
        )
    text = str(exc).strip()
    if text:
        return text
    return type(exc).__name__


def _log_digest_llm_failure(settings: Settings, exc: BaseException) -> None:
    """運用向け。API キーはログに出さない。"""
    if settings.llm_provider == "openai_compatible":
        base = (settings.llm_base_url or "").rstrip("/")
        _logger.warning(
            "digest LLM 呼び出しに失敗 provider=openai_compatible base_url=%s model=%s exc=%r",
            base,
            settings.llm_model,
            exc,
            exc_info=True,
        )
    else:
        _logger.warning(
            "digest LLM 呼び出しに失敗 provider=gemini model=%s exc=%r",
            settings.llm_model,
            exc,
            exc_info=True,
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
        _logger.info(
            "digest LLM リクエスト json_chars=%s user_message_chars=%s timeout_seconds=%s model=%s",
            len(ctx_json),
            len(user_block),
            settings.llm_timeout_seconds,
            settings.llm_model,
        )
        timeout = httpx.Timeout(settings.llm_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            if settings.llm_provider == "openai_compatible":
                summary = await _openai_chat_completion(client, settings, key, user_block)
            else:
                summary = await _gemini_generate_content(client, settings, key, user_block)
        merged = template_markdown.rstrip() + "\n\n" + summary.strip() + "\n"
        return (merged, None)
    except Exception as e:
        _log_digest_llm_failure(settings, e)
        detail = _llm_failure_detail_for_user(e)
        return (template_markdown, f"LLM 要約は省略（{detail}）")


async def _collect_openai_chat_stream_text(response: httpx.Response) -> str:
    """
    OpenAI 互換の ``stream: true`` 応答（SSE ``data: {...}``）から assistant 本文を連結する。

    Ollama は非ストリーミングの長い生成をサーバー側で打ち切り（例: 約 2 分で 500）ことがあるため、
    ストリーミングで受けてトークン間の待ちを避ける。
    """
    parts: list[str] = []
    async for line in response.aiter_lines():
        line = line.strip()
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        payload = line[5:].lstrip()
        if payload == "[DONE]":
            break
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        for choice in data.get("choices") or []:
            delta = choice.get("delta") or {}
            c = delta.get("content")
            if c is not None:
                parts.append(str(c))
    return "".join(parts)


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
        "stream": True,
    }
    async with client.stream("POST", url, headers=headers, json=body) as response:
        if response.status_code >= 400:
            err_body = (await response.aread()).decode("utf-8", errors="replace")[:2000]
            raise RuntimeError(f"HTTP {response.status_code}: {err_body}")
        summary = await _collect_openai_chat_stream_text(response)
    if not summary.strip():
        raise ValueError("OpenAI 互換ストリーミング応答に assistant 本文がありません（choices[].delta.content が空）")
    return summary


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
