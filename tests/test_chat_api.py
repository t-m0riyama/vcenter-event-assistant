"""POST /api/chat のテスト。"""

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
async def test_post_chat_returns_503_when_llm_key_missing(client: AsyncClient) -> None:
    r = await client.post("/api/chat", json=_chat_body())
    assert r.status_code == 503
    assert "LLM" in r.json().get("detail", "")


@pytest.mark.asyncio
async def test_post_chat_returns_400_when_window_inverted(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_DIGEST_API_KEY", "sk-test")
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
    monkeypatch.setenv("LLM_DIGEST_API_KEY", "sk-test")
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
    monkeypatch.setenv("LLM_DIGEST_API_KEY", "sk-test")
    get_settings.cache_clear()

    async def _fake_run(*a: object, **k: object) -> tuple[str, str | None, object]:
        return ("回答テキスト", None, None)

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.run_period_chat",
        _fake_run,
    )

    r = await client.post("/api/chat", json=_chat_body())
    assert r.status_code == 200
    data = r.json()
    assert data["assistant_content"] == "回答テキスト"
    assert data["error"] is None
    assert data.get("llm_context") is None


@pytest.mark.asyncio
async def test_post_chat_returns_llm_context_when_run_period_chat_provides_meta(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_DIGEST_API_KEY", "sk-test")
    get_settings.cache_clear()

    async def _fake_run(*a: object, **k: object) -> tuple[str, str | None, ChatLlmContextMeta]:
        return (
            "回答",
            None,
            ChatLlmContextMeta(
                json_truncated=True,
                estimated_input_tokens=4000,
                max_input_tokens=32000,
                message_turns=1,
            ),
        )

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.run_period_chat",
        _fake_run,
    )

    r = await client.post("/api/chat", json=_chat_body())
    assert r.status_code == 200
    data = r.json()
    ctx = data.get("llm_context")
    assert ctx is not None
    assert ctx["json_truncated"] is True
    assert ctx["estimated_input_tokens"] == 4000
    assert ctx["max_input_tokens"] == 32000
    assert ctx["message_turns"] == 1


@pytest.mark.asyncio
async def test_post_chat_returns_error_field_when_llm_returns_error(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_DIGEST_API_KEY", "sk-test")
    get_settings.cache_clear()

    async def _fake_fail(*a: object, **k: object) -> tuple[str, str | None, object]:
        return ("", "何か失敗", None)

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
async def test_post_chat_calls_period_metrics_builder_when_cpu_toggle_true(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_DIGEST_API_KEY", "sk-test")
    get_settings.cache_clear()

    calls: list[int] = []
    metrics_bucket_sec: list[int] = []
    events_bucket_sec: list[int] = []

    async def _spy(*a: object, **k: object) -> PeriodMetricsPayload:
        calls.append(1)
        metrics_bucket_sec.append(int(k["bucket_sec"]))
        return PeriodMetricsPayload(
            bucket_minutes=15,
            from_utc=datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc),
            to_utc=datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc),
            cpu=[],
        )

    async def _spy_buckets(*a: object, **k: object) -> EventTimeBucketsPayload:
        events_bucket_sec.append(int(k["bucket_sec"]))
        return EventTimeBucketsPayload(
            bucket_minutes=60,
            from_utc=datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc),
            to_utc=datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc),
            buckets=[],
        )

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.build_chat_period_metrics",
        _spy,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.build_chat_event_time_buckets",
        _spy_buckets,
    )

    async def _fake_run(*a: object, **k: object) -> tuple[str, str | None, object]:
        return ("ok", None, None)

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.run_period_chat",
        _fake_run,
    )

    r = await client.post(
        "/api/chat",
        json={**_chat_body(), "include_period_metrics_cpu": True},
    )
    assert r.status_code == 200
    assert len(calls) == 1
    # 24h 窓は既定ルールで 3600 秒バケット。メトリクスとイベントバケットで同一値。
    assert metrics_bucket_sec == [3600]
    assert events_bucket_sec == [3600]


@pytest.mark.asyncio
async def test_post_chat_skips_period_metrics_builder_when_all_toggles_false(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_DIGEST_API_KEY", "sk-test")
    get_settings.cache_clear()

    async def _boom(*a: object, **k: object) -> PeriodMetricsPayload:
        raise AssertionError("build_chat_period_metrics must not be called")

    async def _boom_buckets(*a: object, **k: object) -> EventTimeBucketsPayload:
        raise AssertionError("build_chat_event_time_buckets must not be called")

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.build_chat_period_metrics",
        _boom,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.build_chat_event_time_buckets",
        _boom_buckets,
    )

    async def _fake_run(*a: object, **k: object) -> tuple[str, str | None, object]:
        return ("ok", None, None)

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.run_period_chat",
        _fake_run,
    )

    r = await client.post("/api/chat", json=_chat_body())
    assert r.status_code == 200
