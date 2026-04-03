"""LangChain ChatModel のストリーミング呼び出し（共通）。"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig


async def stream_chat_to_text(
    model: BaseChatModel,
    messages: list[BaseMessage],
    *,
    config: RunnableConfig | None = None,
) -> str:
    """
    ``astream`` でチャンクを連結し、assistant 本文を返す。

    Ollama 等の長い生成では非ストリーミングが打ち切られることがあるためストリーミングを使う。
    一部プロバイダでは ``content`` が文字列ではなくテキストブロックの配列になるため、
    ``str(content)`` は使わず ``text`` で抽出する。
    """
    parts: list[str] = []
    async for chunk in model.astream(messages, config=config):
        if chunk.content:
            parts.append(str(chunk.text))
    text = "".join(parts).strip()
    if not text:
        raise ValueError("LLM ストリーミング応答に assistant 本文がありません（内容が空）")
    return text
