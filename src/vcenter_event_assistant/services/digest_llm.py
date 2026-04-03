"""ダイジェスト用 LLM 呼び出し（LangChain: OpenAI 互換または Google Gemini）。"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from vcenter_event_assistant.services.digest_context import DigestContext
from vcenter_event_assistant.services.llm_factory import build_chat_model
from vcenter_event_assistant.services.llm_invoke import stream_chat_to_text
from vcenter_event_assistant.services.llm_user_errors import _llm_failure_detail_for_user
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


def _trim_context_json(payload: dict[str, Any], *, max_chars: int | None = None) -> str:
    """
    集約 JSON を文字数上限で切り詰める。

    Args:
        payload: LLM に渡す dict（通常は ``DigestContext.model_dump(mode="json")``）。
        max_chars: 上限文字数。未指定時はダイジェスト用の既定（80,000）。チャットはトークン予算に合わせて小さく渡す。
    """
    limit = _MAX_CONTEXT_JSON_CHARS if max_chars is None else max_chars
    raw = json.dumps(payload, ensure_ascii=False)
    if len(raw) <= limit:
        return raw
    return raw[:limit] + "\n…（JSON 長のため切り詰め）"


async def augment_digest_with_llm(
    settings: Settings,
    *,
    context: DigestContext,
    template_markdown: str,
    runnable_config: RunnableConfig | None = None,
) -> tuple[str, str | None]:
    """
    テンプレートに LLM 要約を追記した本文を返す。

    ``runnable_config`` は将来 LangSmith 等の callbacks を渡すための拡張点（未使用でもよい）。

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
        model = build_chat_model(settings, config=runnable_config)
        lc_messages = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user_block)]
        summary = await stream_chat_to_text(model, lc_messages, config=runnable_config)
        merged = template_markdown.rstrip() + "\n\n" + summary.strip() + "\n"
        return (merged, None)
    except Exception as e:
        _log_digest_llm_failure(settings, e)
        detail = _llm_failure_detail_for_user(e)
        return (template_markdown, f"LLM 要約は省略（{detail}）")
