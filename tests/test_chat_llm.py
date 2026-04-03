"""chat_llm.run_period_chat のテスト（LangChain モック）。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from vcenter_event_assistant.api.schemas import ChatMessage
from vcenter_event_assistant.services.chat_event_time_buckets import EventTimeBucketsPayload
from vcenter_event_assistant.services.chat_llm import _CHAT_SYSTEM_PROMPT, run_period_chat
from vcenter_event_assistant.services.chat_period_metrics import PeriodMetricsPayload
from vcenter_event_assistant.services.digest_context import DigestContext, DigestEventTypeBucket
from vcenter_event_assistant.settings import Settings


def _minimal_ctx() -> DigestContext:
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    return DigestContext(
        from_utc=t0,
        to_utc=t0,
        vcenter_count=0,
        total_events=0,
        notable_events_count=0,
        top_notable_event_groups=[],
        top_event_types=[],
        high_cpu_hosts=[],
        high_mem_hosts=[],
    )


@pytest.mark.asyncio
async def test_run_period_chat_skips_http_when_no_api_key() -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key=None,
    )
    out, err, meta = await run_period_chat(
        s,
        context=_minimal_ctx(),
        messages=[ChatMessage(role="user", content="要約して")],
    )
    assert out == ""
    assert err is None
    assert meta is None


@pytest.mark.asyncio
async def test_run_period_chat_openai_sends_multiturn_and_returns_assistant_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key="sk-test",
        llm_provider="openai_compatible",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
    )
    msgs = [
        ChatMessage(role="user", content="最初の質問"),
        ChatMessage(role="assistant", content="仮の答え"),
        ChatMessage(role="user", content="追質問"),
    ]
    captured: dict[str, object] = {}

    def _fake_build(_settings: Settings, *, config: object = None) -> object:
        assert _settings is s
        _ = config
        return object()

    async def _spy_stream_fixed(model: object, messages: object, *, config: object = None) -> str:
        captured["lc_messages"] = messages
        return "追質問への回答"

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_llm.build_chat_model",
        _fake_build,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_llm.stream_chat_to_text",
        _spy_stream_fixed,
    )

    out, err, meta = await run_period_chat(s, context=_minimal_ctx(), messages=msgs)
    assert err is None
    assert out == "追質問への回答"
    assert meta is not None
    assert meta.json_truncated is False
    assert meta.message_turns == 3
    lc = captured["lc_messages"]
    assert isinstance(lc, list)
    assert len(lc) >= 4
    assert isinstance(lc[0], SystemMessage)
    assert lc[0].content == _CHAT_SYSTEM_PROMPT
    assert isinstance(lc[1], HumanMessage)
    assert "```json" in str(lc[1].content)
    assert isinstance(lc[-1], HumanMessage)
    assert lc[-1].content == "追質問"
    assert isinstance(lc[-2], AIMessage)
    assert lc[-2].content == "仮の答え"


@pytest.mark.asyncio
async def test_run_period_chat_gemini_returns_text(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key="gemini-key",
        llm_provider="gemini",
        llm_model="gemini-2.0-flash",
    )
    captured: dict[str, object] = {}

    def _fake_build(_settings: Settings, *, config: object = None) -> object:
        _ = config
        return object()

    async def _spy_stream_fixed(model: object, messages: object, *, config: object = None) -> str:
        captured["lc_messages"] = messages
        return "Gemini の回答"

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_llm.build_chat_model",
        _fake_build,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_llm.stream_chat_to_text",
        _spy_stream_fixed,
    )

    out, err, meta = await run_period_chat(
        s,
        context=_minimal_ctx(),
        messages=[ChatMessage(role="user", content="hello")],
    )
    assert err is None
    assert out == "Gemini の回答"
    assert meta is not None
    assert meta.json_truncated is False
    lc = captured["lc_messages"]
    assert isinstance(lc, list)
    assert isinstance(lc[0], SystemMessage)
    assert isinstance(lc[1], HumanMessage)
    assert "```json" in str(lc[1].content)


@pytest.mark.asyncio
async def test_run_period_chat_truncates_json_when_token_budget_tight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """集約 JSON が推定トークン上限を超えるとき、切り詰めてから API に送る。"""
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key="sk-test",
        llm_provider="openai_compatible",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
        llm_chat_max_input_tokens=2500,
    )
    pad = "x" * 120_000
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    huge_ctx = DigestContext(
        from_utc=t0,
        to_utc=t0,
        vcenter_count=0,
        total_events=0,
        notable_events_count=0,
        top_notable_event_groups=[],
        top_event_types=[
            DigestEventTypeBucket(event_type=pad, event_count=1, max_notable_score=0),
        ],
        high_cpu_hosts=[],
        high_mem_hosts=[],
    )
    captured: dict[str, object] = {}

    def _fake_build(_settings: Settings, *, config: object = None) -> object:
        _ = config
        return object()

    async def _spy_stream_fixed(model: object, messages: object, *, config: object = None) -> str:
        captured["lc_messages"] = messages
        return "ok"

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_llm.build_chat_model",
        _fake_build,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_llm.stream_chat_to_text",
        _spy_stream_fixed,
    )

    out, err, meta = await run_period_chat(
        s,
        context=huge_ctx,
        messages=[ChatMessage(role="user", content="質問")],
    )
    assert err is None
    assert out == "ok"
    assert meta is not None
    assert meta.json_truncated is True
    lc = captured["lc_messages"]
    assert isinstance(lc, list)
    user_block = str(lc[1].content)
    assert "…（JSON 長のため切り詰め）" in user_block
    assert len(user_block) < len(pad)


@pytest.mark.asyncio
async def test_run_period_chat_includes_period_metrics_in_user_block_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key="sk-test",
        llm_provider="openai_compatible",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
    )
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
    pm = PeriodMetricsPayload(
        bucket_minutes=15,
        from_utc=t0,
        to_utc=t1,
        cpu=[],
    )
    captured: dict[str, object] = {}

    def _fake_build(_settings: Settings, *, config: object = None) -> object:
        _ = config
        return object()

    async def _spy_stream_fixed(model: object, messages: object, *, config: object = None) -> str:
        captured["lc_messages"] = messages
        return "y"

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_llm.build_chat_model",
        _fake_build,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_llm.stream_chat_to_text",
        _spy_stream_fixed,
    )

    out, err, meta = await run_period_chat(
        s,
        context=_minimal_ctx(),
        messages=[ChatMessage(role="user", content="q")],
        period_metrics=pm,
    )
    assert err is None
    assert out == "y"
    assert meta is not None
    lc = captured["lc_messages"]
    user_block = str(lc[1].content)
    assert "period_metrics" in user_block
    assert "digest_context" in user_block


@pytest.mark.asyncio
async def test_run_period_chat_includes_event_time_buckets_in_user_block_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key="sk-test",
        llm_provider="openai_compatible",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
    )
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
    etb = EventTimeBucketsPayload(
        bucket_minutes=60,
        from_utc=t0,
        to_utc=t1,
        buckets=[],
    )
    captured: dict[str, object] = {}

    def _fake_build(_settings: Settings, *, config: object = None) -> object:
        _ = config
        return object()

    async def _spy_stream_fixed(model: object, messages: object, *, config: object = None) -> str:
        captured["lc_messages"] = messages
        return "z"

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_llm.build_chat_model",
        _fake_build,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_llm.stream_chat_to_text",
        _spy_stream_fixed,
    )

    out, err, meta = await run_period_chat(
        s,
        context=_minimal_ctx(),
        messages=[ChatMessage(role="user", content="q")],
        event_time_buckets=etb,
    )
    assert err is None
    assert out == "z"
    assert meta is not None
    lc = captured["lc_messages"]
    user_block = str(lc[1].content)
    assert "event_time_buckets" in user_block
    assert "digest_context" in user_block
