"""POST /api/chat のテスト。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

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
async def test_post_chat_returns_503_when_llm_key_missing(client: AsyncClient) -> None:
    r = await client.post("/api/chat", json=_chat_body())
    assert r.status_code == 503
    assert "LLM" in r.json().get("detail", "")


@pytest.mark.asyncio
async def test_post_chat_returns_400_when_window_inverted(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    get_settings.cache_clear()
    r = await client.post(
        "/api/chat",
        json={
            "from": "2026-03-23T00:00:00Z",
            "to": "2026-03-22T00:00:00Z",
            "messages": [{"role": "user", "content": "x"}],
        },
    )
    assert r.status_code == 400
    assert "前" in r.json().get("detail", "")


@pytest.mark.asyncio
async def test_post_chat_returns_422_when_last_message_not_user(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    get_settings.cache_clear()
    r = await client.post(
        "/api/chat",
        json={
            "from": "2026-03-22T00:00:00Z",
            "to": "2026-03-23T00:00:00Z",
            "messages": [
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
            ],
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_chat_returns_assistant_content_when_llm_succeeds(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    get_settings.cache_clear()

    async def _fake_run(*a: object, **k: object) -> tuple[str, str | None]:
        return ("回答テキスト", None)

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.run_period_chat",
        _fake_run,
    )

    r = await client.post("/api/chat", json=_chat_body())
    assert r.status_code == 200
    data = r.json()
    assert data["assistant_content"] == "回答テキスト"
    assert data["error"] is None


@pytest.mark.asyncio
async def test_post_chat_returns_error_field_when_llm_returns_error(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    get_settings.cache_clear()

    async def _fake_fail(*a: object, **k: object) -> tuple[str, str | None]:
        return ("", "何か失敗")

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.run_period_chat",
        _fake_fail,
    )

    r = await client.post("/api/chat", json=_chat_body())
    assert r.status_code == 200
    data = r.json()
    assert data["assistant_content"] == ""
    assert data["error"] == "何か失敗"
