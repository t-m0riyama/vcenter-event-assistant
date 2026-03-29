"""POST /api/chat のテスト。"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from vcenter_event_assistant.services.correlation_context import CpuEventCorrelationPayload
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


@pytest.mark.asyncio
async def test_post_chat_calls_correlation_builder_when_flag_true(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    get_settings.cache_clear()

    calls: list[int] = []

    async def _spy(*a: object, **k: object) -> CpuEventCorrelationPayload:
        calls.append(1)
        return CpuEventCorrelationPayload(cpu_threshold_pct=85.0, window_minutes=15, rows=[])

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.build_cpu_event_correlation",
        _spy,
    )

    async def _fake_run(*a: object, **k: object) -> tuple[str, str | None]:
        return ("ok", None)

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.run_period_chat",
        _fake_run,
    )

    r = await client.post(
        "/api/chat",
        json={**_chat_body(), "include_cpu_event_correlation": True},
    )
    assert r.status_code == 200
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_post_chat_skips_correlation_builder_when_flag_false(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    get_settings.cache_clear()

    async def _boom(*a: object, **k: object) -> CpuEventCorrelationPayload:
        raise AssertionError("build_cpu_event_correlation must not be called")

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.build_cpu_event_correlation",
        _boom,
    )

    async def _fake_run(*a: object, **k: object) -> tuple[str, str | None]:
        return ("ok", None)

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.run_period_chat",
        _fake_run,
    )

    r = await client.post("/api/chat", json=_chat_body())
    assert r.status_code == 200
