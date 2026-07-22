"""chat_llm_payload の characterization テスト（LLM モック不要）。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from vcenter_event_assistant.api.schemas import ChatMessage
from vcenter_event_assistant.services.chat.chat_event_time_buckets import EventTimeBucketsPayload
from vcenter_event_assistant.services.chat.chat_incident_timeline import IncidentTimelineColumn, IncidentTimelinePayload
from vcenter_event_assistant.services.chat.chat_llm_payload import (
    CHAT_SYSTEM_PROMPT,
    CHAT_WEB_SEARCH_GUIDANCE,
    build_chat_llm_context,
    compose_chat_system_prompt,
    fit_chat_payload_to_token_budget,
    prepare_chat_payload,
)
from vcenter_event_assistant.services.chat.chat_period_metrics import PeriodMetricsPayload
from vcenter_event_assistant.services.digest.digest_context import DigestContext, DigestNotableEventGroup
from vcenter_event_assistant.settings import Settings


def _minimal_ctx(**kwargs: object) -> DigestContext:
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    defaults = {
        "from_utc": t0,
        "to_utc": t0,
        "vcenter_count": 0,
        "total_events": 0,
        "notable_events_count": 0,
        "top_notable_event_groups": [],
        "top_event_types": [],
        "high_cpu_hosts": [],
        "high_mem_hosts": [],
    }
    defaults.update(kwargs)
    return DigestContext(**defaults)  # type: ignore[arg-type]


def test_compose_chat_system_prompt_appends_guidance_only_when_enabled() -> None:
    base = compose_chat_system_prompt(enable_web_search=False)
    with_search = compose_chat_system_prompt(enable_web_search=True)
    assert base == CHAT_SYSTEM_PROMPT
    assert "【WEB 検索ツール】" not in base
    assert with_search == CHAT_SYSTEM_PROMPT + CHAT_WEB_SEARCH_GUIDANCE
    assert "検索してよい例" in with_search
    assert "検索しない例" in with_search
    assert "NSX" in with_search


def test_prepare_chat_payload_excludes_high_cpu_mem_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(database_url="sqlite+aiosqlite:///:memory:", llm_anonymization_enabled=False)
    monkeypatch.setattr("vcenter_event_assistant.services.chat.chat_llm_payload.require_settings", lambda: s)
    ctx = _minimal_ctx(
        high_cpu_hosts=[],
        high_mem_hosts=[],
    )
    payload, trimmed, reverse_map = prepare_chat_payload(
        ctx,
        [ChatMessage(role="user", content="hello")],
        period_metrics=None,
        event_time_buckets=None,
        incident_timeline=None,
        extra_vcenter_strings=None,
    )
    digest = payload["digest_context"]
    assert "high_cpu_hosts" not in digest
    assert "high_mem_hosts" not in digest
    assert trimmed == [ChatMessage(role="user", content="hello")]
    assert reverse_map == {}


def test_prepare_chat_payload_includes_optional_blocks_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = Settings(database_url="sqlite+aiosqlite:///:memory:", llm_anonymization_enabled=False)
    monkeypatch.setattr("vcenter_event_assistant.services.chat.chat_llm_payload.require_settings", lambda: s)
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
    pm = PeriodMetricsPayload(bucket_minutes=15, from_utc=t0, to_utc=t1, cpu=[])
    etb = EventTimeBucketsPayload(bucket_minutes=60, from_utc=t0, to_utc=t1, buckets=[])
    timeline = IncidentTimelinePayload(
        columns=[
            IncidentTimelineColumn(
                timestamp_utc=t0,
                visible_items=[],
                hidden_count=0,
            ),
        ],
    )
    payload, _, _ = prepare_chat_payload(
        _minimal_ctx(),
        [ChatMessage(role="user", content="q")],
        period_metrics=pm,
        event_time_buckets=etb,
        incident_timeline=timeline,
        extra_vcenter_strings=None,
    )
    assert "period_metrics" in payload
    assert "event_time_buckets" in payload
    assert "incident_timeline" in payload


def test_fit_chat_payload_to_token_budget_truncates_large_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_chat_max_input_tokens=2500,
    )
    monkeypatch.setattr("vcenter_event_assistant.services.chat.chat_llm_payload.require_settings", lambda: s)
    pad = "x" * 120_000
    payload = {
        "digest_context": {
            "from_utc": "2026-03-22T00:00:00+00:00",
            "to_utc": "2026-03-22T00:00:00+00:00",
            "top_event_types": [{"event_type": pad, "event_count": 1, "max_notable_score": 0}],
        },
    }
    ctx_json, trimmed, json_truncated = fit_chat_payload_to_token_budget(
        payload,
        [ChatMessage(role="user", content="質問")],
    )
    assert json_truncated is True
    assert "…（JSON 長のため切り詰め）" in ctx_json
    assert len(ctx_json) < len(pad)
    assert trimmed == [ChatMessage(role="user", content="質問")]


def test_build_chat_llm_context_returns_meta_without_llm_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_chat_max_input_tokens=8000,
        llm_anonymization_enabled=False,
    )
    monkeypatch.setattr("vcenter_event_assistant.services.chat.chat_llm_payload.require_settings", lambda: s)
    block, trimmed, meta, reverse_map = build_chat_llm_context(
        _minimal_ctx(),
        [ChatMessage(role="user", content="ping")],
        period_metrics=None,
        event_time_buckets=None,
        incident_timeline=None,
        extra_vcenter_strings=None,
    )
    assert "```json" in block
    assert "digest_context" in block
    assert meta is not None
    assert meta.json_truncated is False
    assert meta.message_turns == 1
    assert meta.estimated_input_tokens <= meta.max_input_tokens
    assert reverse_map == {}


def test_build_chat_llm_context_anonymizes_entity_names_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_anonymization_enabled=True,
    )
    monkeypatch.setattr("vcenter_event_assistant.services.chat.chat_llm_payload.require_settings", lambda: s)
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    secret = "SECRET-ESXI-01.example.com"
    ctx = _minimal_ctx(
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
            ),
        ],
    )
    block, _, _, _ = build_chat_llm_context(
        ctx,
        [ChatMessage(role="user", content="状況は")],
        period_metrics=None,
        event_time_buckets=None,
        incident_timeline=None,
        extra_vcenter_strings=None,
    )
    assert secret not in block
