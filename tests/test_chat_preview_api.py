"""POST /api/chat/preview のテスト。"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest
from httpx import AsyncClient

from vcenter_event_assistant.api.schemas import ChatLlmContextMeta
from vcenter_event_assistant.services.chat_event_time_buckets import EventTimeBucketsPayload
from vcenter_event_assistant.services.chat_period_metrics import PeriodMetricsPayload
from vcenter_event_assistant.settings import get_settings


def _chat_body(**overrides: object) -> dict:
    base = {
        "from": "2026-03-22T00:00:00Z",
        "to": "2026-03-23T00:00:00Z",
        "messages": [{"role": "user", "content": "質問"}],
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_post_chat_preview_success(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_DIGEST_API_KEY", "sk-test")
    get_settings.cache_clear()

    def _fake_build(*a: object, **k: object) -> tuple[str, list, ChatLlmContextMeta | None]:
        from vcenter_event_assistant.api.schemas import ChatMessage
        return (
            "プレビュー用コンテキストブロック",
            [ChatMessage(role="user", content="質問")],
            ChatLlmContextMeta(
                json_truncated=False,
                estimated_input_tokens=100,
                max_input_tokens=1000,
                message_turns=1,
            )
        )

    # _fake_build をパッチする箇所については次のステップでの機能実装後に調整する
    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.build_chat_preview",
        _fake_build,
        raising=False
    )

    resp = await client.post("/api/chat/preview", json=_chat_body())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "context_block" in data
    assert "conversation" in data
    assert "llm_context" in data
    assert data["context_block"] == "プレビュー用コンテキストブロック"
