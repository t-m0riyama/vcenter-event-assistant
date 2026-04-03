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

    ``config`` は将来 LangSmith 等の callbacks を ``ainvoke`` / ``astream`` に渡すための拡張点。
    モデル構築時には未使用でもよい。
    """
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
