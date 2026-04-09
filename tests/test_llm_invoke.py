"""llm_invoke.stream_chat_to_text のテスト。"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessageChunk, HumanMessage

from vcenter_event_assistant.services.llm_invoke import stream_chat_to_text


@pytest.mark.asyncio
async def test_stream_chat_to_text_joins_plain_text_from_content_blocks() -> None:
    """Gemini 等: チャンクの content が list[dict] のときもプレーンテキストとして連結する。"""
    chunks = [
        AIMessageChunk(content=[{"type": "text", "text": "あ", "index": 0}]),
        AIMessageChunk(content=[{"type": "text", "text": "い", "index": 0}]),
    ]

    class _FakeStreamModel:
        async def astream(self, messages: object, config: object = None):
            _ = messages
            _ = config
            for c in chunks:
                yield c

    text, lat, tps = await stream_chat_to_text(
        _FakeStreamModel(),  # type: ignore[arg-type]
        [HumanMessage("hi")],
    )
    assert text == "あい"
    assert "[" not in text
