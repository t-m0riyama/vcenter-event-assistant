"""Settings から LangChain ChatModel を組み立てる。"""

from __future__ import annotations

from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig

from vcenter_event_assistant.services.llm_profile import resolve_llm_profile
from vcenter_event_assistant.settings import Settings

LlmPurpose = Literal["digest", "chat"]


def build_chat_model(
    settings: Settings,
    *,
    purpose: LlmPurpose,
    config: RunnableConfig | None = None,
) -> BaseChatModel:
    """
    LLM 設定に応じて ChatModel を返す。

    Args:
        settings: アプリ設定（ダイジェスト用・チャット用の解決済みフィールド）。
        purpose: ``digest`` は ``LLM_DIGEST_*`` のみ、``chat`` は ``LLM_CHAT_*`` をマージした実効値。
        config: 呼び出し側で ``stream_chat_to_text`` / ``ainvoke`` / ``astream`` に渡す
            ``RunnableConfig``（callbacks 等）用。モデルコンストラクタにはバインドしない。
            **本関数内では使用しない**（将来、モデル生成時にメタデータを付けたい場合のシグネチャ互換のため受け取る）。
    """
    _ = config
    p = resolve_llm_profile(settings, purpose=purpose)
    key = p.api_key
    if p.provider == "copilot_cli":
        raise ValueError(
            "copilot_cli は LangChain ChatModel では使用できません。"
            "チャットは chat_llm の Copilot 専用分岐を使用してください。"
        )
    if p.provider == "openai_compatible":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=p.model,
            api_key=key,
            base_url=p.base_url.rstrip("/"),
            timeout=p.timeout_seconds,
        )
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=p.model,
        google_api_key=key,
        timeout=p.timeout_seconds,
    )
