"""Settings から LangChain ChatModel を組み立てる。"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig

from vcenter_event_assistant.settings import Settings


def build_chat_model(
    settings: Settings,
    *,
    config: RunnableConfig | None = None,
) -> BaseChatModel:
    """
    LLM 設定に応じて ChatModel を返す。

    Args:
        settings: アプリ設定（プロバイダ・モデル・API キー・タイムアウト等）。
        config: 呼び出し側で ``stream_chat_to_text`` / ``ainvoke`` / ``astream`` に渡す
            ``RunnableConfig``（callbacks 等）用。モデルコンストラクタにはバインドしない。
            **本関数内では使用しない**（将来、モデル生成時にメタデータを付けたい場合のシグネチャ互換のため受け取る）。
    """
    # callbacks は invoke 時に渡す。ここでは ChatModel 生成のみ。
    _ = config
    key = (settings.llm_api_key or "").strip()
    if settings.llm_provider == "openai_compatible":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.llm_model,
            api_key=key,
            base_url=settings.llm_base_url.rstrip("/"),
            timeout=settings.llm_timeout_seconds,
        )
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=settings.llm_model,
        google_api_key=key,
        timeout=settings.llm_timeout_seconds,
    )
