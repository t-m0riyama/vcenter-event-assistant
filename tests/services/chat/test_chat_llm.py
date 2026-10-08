"""chat_llm.run_period_chat のテスト（LangChain モック）。"""

from __future__ import annotations

import base64
from datetime import datetime, timezone

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from vcenter_event_assistant.api.schemas import ChatAttachment, ChatMessage
from vcenter_event_assistant.services.chat.chat_event_time_buckets import (
    EventTimeBucketsPayload,
)
from vcenter_event_assistant.services.chat.chat_incident_timeline import (
    IncidentTimelineColumn,
    IncidentTimelinePayload,
)
from vcenter_event_assistant.services.chat.chat_llm import (
    _CHAT_SYSTEM_PROMPT,
    run_period_chat,
)
from vcenter_event_assistant.services.chat.chat_period_metrics import (
    PeriodMetricsPayload,
)
from vcenter_event_assistant.services.digest.digest_context import (
    DigestContext,
    DigestEventTypeBucket,
    DigestNotableEventGroup,
)
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


def test_chat_system_prompt_forbids_internal_lm_tokens_in_answer() -> None:
    """応答に内部匿名化トークン（__LM_*）を出さず、括弧で別名を足さない旨が含まれる。"""
    assert "__LM_" in _CHAT_SYSTEM_PROMPT
    assert "括弧" in _CHAT_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_run_period_chat_skips_http_when_no_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key=None,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.require_settings", lambda: s
    )
    out, err, meta, _, _ = await run_period_chat(
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
        llm_digest_api_key="sk-test",
        llm_digest_provider="openai_compatible",
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="gpt-4o-mini",
    )
    msgs = [
        ChatMessage(role="user", content="最初の質問"),
        ChatMessage(role="assistant", content="仮の答え"),
        ChatMessage(role="user", content="追質問"),
    ]
    captured: dict[str, object] = {}

    def _fake_build(
        _settings: Settings, *, purpose: object = None, config: object = None
    ) -> object:
        assert _settings is s
        _ = purpose
        _ = config
        return object()

    async def _spy_stream_fixed(
        model: object, messages: object, *, config: object = None
    ) -> tuple[str, int | None, float | None]:
        captured["lc_messages"] = messages
        return "追質問への回答", None, None

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.build_chat_model",
        _fake_build,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.stream_chat_to_text",
        _spy_stream_fixed,
    )

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.require_settings", lambda: s
    )
    out, err, meta, _, _ = await run_period_chat(context=_minimal_ctx(), messages=msgs)
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
async def test_run_period_chat_passes_runnable_config_to_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key="sk-test",
        llm_digest_provider="openai_compatible",
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="gpt-4o-mini",
    )
    captured: dict[str, object] = {}

    def _fake_build(
        _settings: Settings, *, purpose: object = None, config: object = None
    ) -> object:
        _ = purpose
        _ = config
        return object()

    async def _spy_stream(
        model: object,
        messages: object,
        *,
        config: object = None,
    ) -> tuple[str, int | None, float | None]:
        captured["config"] = config
        return "ok", None, None

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.build_chat_model",
        _fake_build,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.stream_chat_to_text",
        _spy_stream,
    )

    cfg = {"metadata": {"x": 1}}
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.require_settings", lambda: s
    )
    await run_period_chat(
        context=_minimal_ctx(),
        messages=[ChatMessage(role="user", content="ping")],
        runnable_config=cfg,
    )
    assert captured.get("config") == cfg


@pytest.mark.asyncio
async def test_run_period_chat_gemini_returns_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key="gemini-key",
        llm_digest_provider="gemini",
        llm_digest_model="gemini-2.0-flash",
    )
    captured: dict[str, object] = {}

    def _fake_build(
        _settings: Settings, *, purpose: object = None, config: object = None
    ) -> object:
        _ = purpose
        _ = config
        return object()

    async def _spy_stream_fixed(
        model: object, messages: object, *, config: object = None
    ) -> tuple[str, int | None, float | None]:
        captured["lc_messages"] = messages
        return "Gemini の回答", None, None

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.build_chat_model",
        _fake_build,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.stream_chat_to_text",
        _spy_stream_fixed,
    )

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.require_settings", lambda: s
    )
    out, err, meta, _, _ = await run_period_chat(
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
        llm_digest_api_key="sk-test",
        llm_digest_provider="openai_compatible",
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="gpt-4o-mini",
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

    def _fake_build(
        _settings: Settings, *, purpose: object = None, config: object = None
    ) -> object:
        _ = purpose
        _ = config
        return object()

    async def _spy_stream_fixed(
        model: object, messages: object, *, config: object = None
    ) -> tuple[str, int | None, float | None]:
        captured["lc_messages"] = messages
        return "ok", None, None

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.build_chat_model",
        _fake_build,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.stream_chat_to_text",
        _spy_stream_fixed,
    )

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.require_settings", lambda: s
    )
    out, err, meta, _, _ = await run_period_chat(
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
        llm_digest_api_key="sk-test",
        llm_digest_provider="openai_compatible",
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="gpt-4o-mini",
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

    def _fake_build(
        _settings: Settings, *, purpose: object = None, config: object = None
    ) -> object:
        _ = purpose
        _ = config
        return object()

    async def _spy_stream_fixed(
        model: object, messages: object, *, config: object = None
    ) -> tuple[str, int | None, float | None]:
        captured["lc_messages"] = messages
        return "y", None, None

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.build_chat_model",
        _fake_build,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.stream_chat_to_text",
        _spy_stream_fixed,
    )

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.require_settings", lambda: s
    )
    out, err, meta, _, _ = await run_period_chat(
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
        llm_digest_api_key="sk-test",
        llm_digest_provider="openai_compatible",
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="gpt-4o-mini",
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

    def _fake_build(
        _settings: Settings, *, purpose: object = None, config: object = None
    ) -> object:
        _ = purpose
        _ = config
        return object()

    async def _spy_stream_fixed(
        model: object, messages: object, *, config: object = None
    ) -> tuple[str, int | None, float | None]:
        captured["lc_messages"] = messages
        return "z", None, None

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.build_chat_model",
        _fake_build,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.stream_chat_to_text",
        _spy_stream_fixed,
    )

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.require_settings", lambda: s
    )
    out, err, meta, _, _ = await run_period_chat(
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


@pytest.mark.asyncio
async def test_run_period_chat_includes_incident_timeline_in_user_block_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key="sk-test",
        llm_digest_provider="openai_compatible",
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="gpt-4o-mini",
    )
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    timeline = IncidentTimelinePayload(
        columns=[
            IncidentTimelineColumn(
                timestamp_utc=t0,
                visible_items=[],
                hidden_count=0,
            )
        ]
    )
    captured: dict[str, object] = {}

    def _fake_build(
        _settings: Settings, *, purpose: object = None, config: object = None
    ) -> object:
        _ = purpose
        _ = config
        return object()

    async def _spy_stream_fixed(
        model: object, messages: object, *, config: object = None
    ) -> tuple[str, int | None, float | None]:
        captured["lc_messages"] = messages
        return "incident", None, None

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.build_chat_model",
        _fake_build,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.stream_chat_to_text",
        _spy_stream_fixed,
    )

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.require_settings", lambda: s
    )
    out, err, meta, _, _ = await run_period_chat(
        context=_minimal_ctx(),
        messages=[ChatMessage(role="user", content="q")],
        incident_timeline=timeline,
    )
    assert err is None
    assert out == "incident"
    assert meta is not None
    lc = captured["lc_messages"]
    user_block = str(lc[1].content)
    assert "incident_timeline" in user_block
    assert "digest_context" in user_block


@pytest.mark.asyncio
async def test_run_period_chat_anonymizes_entity_names_sent_to_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """匿名化オン時、コンテキスト JSON に含まれる entity 名が LLM 入力ブロックに出ないこと。"""
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key="sk-test",
        llm_digest_provider="openai_compatible",
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="gpt-4o-mini",
        llm_anonymization_enabled=True,
    )
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    secret = "SECRET-ESXI-01.example.com"
    ctx = DigestContext(
        from_utc=t0,
        to_utc=t0,
        vcenter_count=1,
        total_events=1,
        notable_events_count=1,
        top_notable_event_groups=[
            DigestNotableEventGroup(
                event_type="vim.event.Event",
                occurrence_count=1,
                notable_score=50,
                occurred_at_first=t0,
                occurred_at_last=t0,
                entity_name=secret,
                message="ping",
            )
        ],
        top_event_types=[],
        high_cpu_hosts=[],
        high_mem_hosts=[],
    )
    captured: dict[str, object] = {}

    def _fake_build(
        _settings: Settings, *, purpose: object = None, config: object = None
    ) -> object:
        _ = purpose
        _ = config
        return object()

    async def _spy_stream_fixed(
        model: object, messages: object, *, config: object = None
    ) -> tuple[str, int | None, float | None]:
        captured["lc_messages"] = messages
        return "ok", None, None

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.build_chat_model",
        _fake_build,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.stream_chat_to_text",
        _spy_stream_fixed,
    )

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.require_settings", lambda: s
    )
    await run_period_chat(
        context=ctx,
        messages=[ChatMessage(role="user", content="状況は")],
    )
    lc = captured["lc_messages"]
    user_block = str(lc[1].content)
    assert secret not in user_block


@pytest.mark.asyncio
async def test_run_period_chat_anonymizes_extra_vcenter_strings_in_user_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """集約 JSON に無い登録 vCenter 名も ``extra_vcenter_strings`` で会話から除去する。"""
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key="sk-test",
        llm_digest_provider="openai_compatible",
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="gpt-4o-mini",
        llm_anonymization_enabled=True,
    )
    display = "REG-VCENTER-DISPLAY-ONLY"
    short_label = "vc-short-label"
    captured: dict[str, object] = {}

    def _fake_build(
        _settings: Settings, *, purpose: object = None, config: object = None
    ) -> object:
        _ = purpose
        _ = config
        return object()

    async def _spy_stream_fixed(
        model: object, messages: object, *, config: object = None
    ) -> tuple[str, int | None, float | None]:
        captured["lc_messages"] = messages
        return "ok", None, None

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.build_chat_model",
        _fake_build,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.stream_chat_to_text",
        _spy_stream_fixed,
    )

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.require_settings", lambda: s
    )
    await run_period_chat(
        context=_minimal_ctx(),
        messages=[
            ChatMessage(
                role="user",
                content=f"{display} と {short_label} の状態",
            ),
        ],
        extra_vcenter_strings=[display, "vc.full.example.com", short_label],
    )
    lc = captured["lc_messages"]
    joined = str(lc)
    assert display not in joined
    assert short_label not in joined


@pytest.mark.asyncio
async def test_run_period_chat_respects_llm_anonymization_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """匿名化オフ時は実名が LLM 入力に残る（従来挙動）。"""
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key="sk-test",
        llm_digest_provider="openai_compatible",
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="gpt-4o-mini",
        llm_anonymization_enabled=False,
    )
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    secret = "PLAIN-HOST-01"
    ctx = DigestContext(
        from_utc=t0,
        to_utc=t0,
        vcenter_count=1,
        total_events=1,
        notable_events_count=1,
        top_notable_event_groups=[
            DigestNotableEventGroup(
                event_type="vim.event.Event",
                occurrence_count=1,
                notable_score=50,
                occurred_at_first=t0,
                occurred_at_last=t0,
                entity_name=secret,
                message="ping",
            )
        ],
        top_event_types=[],
        high_cpu_hosts=[],
        high_mem_hosts=[],
    )
    captured: dict[str, object] = {}

    def _fake_build(
        _settings: Settings, *, purpose: object = None, config: object = None
    ) -> object:
        _ = purpose
        _ = config
        return object()

    async def _spy_stream_fixed(
        model: object, messages: object, *, config: object = None
    ) -> tuple[str, int | None, float | None]:
        captured["lc_messages"] = messages
        return "ok", None, None

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.build_chat_model",
        _fake_build,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.stream_chat_to_text",
        _spy_stream_fixed,
    )

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.require_settings", lambda: s
    )
    await run_period_chat(
        context=ctx,
        messages=[ChatMessage(role="user", content="状況は")],
    )
    lc = captured["lc_messages"]
    assert secret in str(lc[1].content)


@pytest.mark.asyncio
async def test_run_period_chat_web_search_appends_sources_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """enable_web_search + プロバイダ構成済みでツールループを使い、出典ブロックを連結する。"""
    from vcenter_event_assistant.services.research.search_provider import (
        WebSearchResult,
    )

    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key="sk-test",
        llm_digest_provider="openai_compatible",
        tavily_api_key="tvly-test",
        web_research_enabled=True,
    )

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.build_chat_model",
        lambda _s, *, purpose=None, config=None: object(),
    )

    async def _fake_web_search_run(
        model: object,
        lc_messages: object,
        provider: object,
        settings: object,
        *,
        scope: object = None,
        config: object = None,
    ) -> tuple[str, list[WebSearchResult]]:
        captured["lc_messages"] = lc_messages
        captured["scope"] = scope
        _ = model, provider, settings, config
        return "検索を踏まえた回答", [
            WebSearchResult(title="KB 9", url="https://example.com/kb9", snippet="")
        ]

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.run_chat_with_web_search",
        _fake_web_search_run,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.require_settings", lambda: s
    )

    out, err, _, latency_ms, _ = await run_period_chat(
        context=_minimal_ctx(),
        messages=[ChatMessage(role="user", content="この障害を調べて")],
        enable_web_search=True,
        web_search_scope="incidents",
        web_search_aggressiveness="conservative",
    )
    assert err is None
    assert out.startswith("検索を踏まえた回答")
    assert "## WEB 検索の出典" in out
    assert "- [KB 9](https://example.com/kb9)" in out
    assert latency_ms is not None
    assert captured.get("scope") == "incidents"
    lc = captured["lc_messages"]
    assert isinstance(lc, list)
    assert isinstance(lc[0], SystemMessage)
    assert "【WEB 検索ツール】" in str(lc[0].content)
    assert "明確に必要" in str(lc[0].content)
    assert "NSX" not in str(lc[0].content)


@pytest.mark.asyncio
async def test_run_period_chat_web_search_ignored_without_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """enable_web_search でも検索プロバイダ未構成なら従来のストリーミング経路。"""
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key="sk-test",
        llm_digest_provider="openai_compatible",
    )

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.build_chat_model",
        lambda _s, *, purpose=None, config=None: object(),
    )

    async def _spy_stream(
        model: object, messages: object, *, config: object = None
    ) -> tuple[str, int | None, float | None]:
        captured["lc_messages"] = messages
        return "通常の回答", None, None

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.stream_chat_to_text",
        _spy_stream,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.require_settings", lambda: s
    )

    out, err, _, _, _ = await run_period_chat(
        context=_minimal_ctx(),
        messages=[ChatMessage(role="user", content="q")],
        enable_web_search=True,
    )
    assert err is None
    assert out == "通常の回答"
    lc = captured["lc_messages"]
    assert isinstance(lc, list)
    assert isinstance(lc[0], SystemMessage)
    assert lc[0].content == _CHAT_SYSTEM_PROMPT
    assert "【WEB 検索ツール】" not in str(lc[0].content)


# --- 添付ファイル ---

_PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 32).decode()


def _text_attachment(body: str = "kernel panic at 03:00") -> ChatAttachment:
    return ChatAttachment(
        kind="text", filename="vmkernel.log", media_type="text/plain", text=body
    )


def _image_attachment() -> ChatAttachment:
    return ChatAttachment(
        kind="image", filename="shot.png", media_type="image/png", data_base64=_PNG_B64
    )


def _openai_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "sqlite+aiosqlite:///:memory:",
        "llm_digest_api_key": "sk-test",
        "llm_digest_provider": "openai_compatible",
        "llm_digest_base_url": "https://api.openai.com/v1",
        "llm_digest_model": "gpt-4o-mini",
        "llm_anonymization_enabled": False,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _spy_langchain(
    monkeypatch: pytest.MonkeyPatch, captured: dict[str, object]
) -> None:
    async def _spy_stream(
        model: object, messages: object, *, config: object = None
    ) -> tuple[str, int | None, float | None]:
        captured["lc_messages"] = messages
        return "回答", None, None

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.build_chat_model",
        lambda _s, *, purpose=None, config=None: object(),
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.stream_chat_to_text",
        _spy_stream,
    )


@pytest.mark.asyncio
async def test_run_period_chat_sends_text_attachment_as_its_own_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _openai_settings()
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.require_settings", lambda: s
    )
    captured: dict[str, object] = {}
    _spy_langchain(monkeypatch, captured)

    _out, err, meta, _, _ = await run_period_chat(
        context=_minimal_ctx(),
        messages=[ChatMessage(role="user", content="何が起きた？")],
        attachments=[_text_attachment()],
    )
    assert err is None
    lc = captured["lc_messages"]
    assert isinstance(lc, list)
    # system, 集約 JSON, 添付, 質問
    assert len(lc) == 4
    assert isinstance(lc[2], HumanMessage)
    assert "vmkernel.log" in lc[2].content
    assert "kernel panic at 03:00" in lc[2].content
    assert meta is not None
    assert meta.attachment_count == 1
    assert meta.attachments_dropped_reason is None


@pytest.mark.asyncio
async def test_run_period_chat_puts_image_on_last_user_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _openai_settings()
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.require_settings", lambda: s
    )
    captured: dict[str, object] = {}
    _spy_langchain(monkeypatch, captured)

    _out, err, meta, _, _ = await run_period_chat(
        context=_minimal_ctx(),
        messages=[
            ChatMessage(role="user", content="前の質問"),
            ChatMessage(role="assistant", content="前の答え"),
            ChatMessage(role="user", content="この画面は？"),
        ],
        attachments=[_image_attachment()],
    )
    assert err is None
    lc = captured["lc_messages"]
    assert isinstance(lc, list)
    last = lc[-1]
    assert isinstance(last, HumanMessage)
    assert last.content == [
        {"type": "text", "text": "この画面は？"},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_PNG_B64}"}},
    ]
    # 過去の user メッセージは素のテキストのまま
    assert lc[-3].content == "前の質問"
    assert meta is not None
    assert meta.attachment_count == 1


@pytest.mark.asyncio
async def test_run_period_chat_drops_images_for_copilot_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_provider="copilot_cli",
        llm_copilot_cli_session_auth=True,
        llm_anonymization_enabled=False,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.require_settings", lambda: s
    )
    captured: dict[str, object] = {}

    async def _fake_copilot(
        _s: Settings, *, system_prompt: str, block: str, messages: object
    ) -> str:
        captured["block"] = block
        return "CLI からの回答"

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.run_copilot_cli_chat_completion",
        _fake_copilot,
    )

    out, err, meta, _, _ = await run_period_chat(
        context=_minimal_ctx(),
        messages=[ChatMessage(role="user", content="この画面は？")],
        attachments=[_image_attachment(), _text_attachment()],
    )
    assert err is None
    assert meta is not None
    assert meta.attachments_dropped_reason is not None
    assert "画像" in meta.attachments_dropped_reason
    # 画像は落ちるがテキスト添付はプロンプトに載る
    assert meta.attachment_count == 1
    assert "vmkernel.log" in str(captured["block"])
    # 利用者に無視した旨を伝える
    assert meta.attachments_dropped_reason in out
    assert "CLI からの回答" in out


@pytest.mark.asyncio
async def test_run_period_chat_anonymizes_attachment_text_with_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """添付本文と会話本文が同一の匿名化トークンになる。"""
    s = _openai_settings(llm_anonymization_enabled=True)
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm.require_settings", lambda: s
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm_payload.require_settings",
        lambda: s,
    )
    captured: dict[str, object] = {}
    _spy_langchain(monkeypatch, captured)

    await run_period_chat(
        context=_minimal_ctx(),
        messages=[ChatMessage(role="user", content="10.1.2.3 で何が起きた？")],
        attachments=[_text_attachment(body="host 10.1.2.3 down")],
        extra_vcenter_strings=None,
    )
    lc = captured["lc_messages"]
    assert isinstance(lc, list)
    attachment_text = str(lc[2].content)
    question_text = str(lc[3].content)
    assert "10.1.2.3" not in attachment_text
    assert "10.1.2.3" not in question_text
    token = "__LM_IP_001__"
    assert token in attachment_text
    assert token in question_text
