"""chat_llm_payload の characterization テスト（LLM モック不要）。"""

from __future__ import annotations

import base64
from datetime import datetime, timezone

import pytest

from vcenter_event_assistant.api.schemas import ChatAttachment, ChatMessage
from vcenter_event_assistant.services.chat.chat_event_time_buckets import EventTimeBucketsPayload
from vcenter_event_assistant.services.chat.chat_incident_timeline import IncidentTimelineColumn, IncidentTimelinePayload
from vcenter_event_assistant.services.chat.chat_attachments import (
    ATTACHMENT_TRUNCATION_SUFFIX,
    IMAGE_TOKENS_PER_ATTACHMENT,
)
from vcenter_event_assistant.services.chat.chat_llm_payload import (
    CHAT_SYSTEM_PROMPT,
    CHAT_WEB_SEARCH_GUIDANCE,
    build_chat_llm_context,
    compose_chat_system_prompt,
    compose_web_search_guidance,
    estimate_chat_input_tokens,
    fit_chat_payload_to_token_budget,
    merged_context_user_block,
    prepare_chat_payload,
    web_search_tool_description,
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


def test_compose_chat_system_prompt_varies_by_scope_and_aggressiveness() -> None:
    incidents = compose_chat_system_prompt(
        enable_web_search=True, scope="incidents", aggressiveness="conservative"
    )
    ecosystem = compose_chat_system_prompt(
        enable_web_search=True, scope="vmware_ecosystem", aggressiveness="aggressive"
    )
    assert "障害・イベント" in incidents
    assert "NSX" not in incidents
    assert "明確に必要" in incidents
    assert "NSX" in ecosystem
    assert "答えの質が上がりそう" in ecosystem
    assert incidents != ecosystem


def test_web_search_tool_description_varies_by_scope() -> None:
    incidents = web_search_tool_description("incidents")
    ops = web_search_tool_description("vsphere_ops")
    eco = web_search_tool_description("vmware_ecosystem")
    assert "障害・イベント" in incidents
    assert "NSX" not in incidents
    assert "設定手順" in ops
    assert "NSX" in eco
    assert "固有" in eco
    assert compose_web_search_guidance() == CHAT_WEB_SEARCH_GUIDANCE


def test_prepare_chat_payload_excludes_high_cpu_mem_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(database_url="sqlite+aiosqlite:///:memory:", llm_anonymization_enabled=False)
    monkeypatch.setattr("vcenter_event_assistant.services.chat.chat_llm_payload.require_settings", lambda: s)
    ctx = _minimal_ctx(
        high_cpu_hosts=[],
        high_mem_hosts=[],
    )
    payload, trimmed, attachment_block, reverse_map = prepare_chat_payload(
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
    assert attachment_block is None
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
    payload, _, _, _ = prepare_chat_payload(
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
    ctx_json, trimmed, json_truncated, _, _ = fit_chat_payload_to_token_budget(
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
    result = build_chat_llm_context(
        _minimal_ctx(),
        [ChatMessage(role="user", content="ping")],
        period_metrics=None,
        event_time_buckets=None,
        incident_timeline=None,
        extra_vcenter_strings=None,
    )
    block, meta, reverse_map = result.block, result.meta, result.reverse_map
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
    block = build_chat_llm_context(
        ctx,
        [ChatMessage(role="user", content="状況は")],
        period_metrics=None,
        event_time_buckets=None,
        incident_timeline=None,
        extra_vcenter_strings=None,
    ).block
    assert secret not in block


# --- 添付ファイル ---


def _text_attachment(name: str = "big.log", body: str = "x") -> ChatAttachment:
    return ChatAttachment(kind="text", filename=name, media_type="text/plain", text=body)


def test_estimate_chat_input_tokens_counts_attachments_and_images() -> None:
    base = estimate_chat_input_tokens("block", [])
    with_text = estimate_chat_input_tokens("block", [], "添付本文", 0)
    with_image = estimate_chat_input_tokens("block", [], None, 1)
    assert with_text > base
    assert with_image == base + IMAGE_TOKENS_PER_ATTACHMENT


def test_fit_chat_payload_trims_conversation_before_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """添付は利用者がいま尋ねている対象なので、古い会話より後に削る。"""
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_chat_max_input_tokens=2500,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm_payload.require_settings", lambda: s
    )
    payload = {"digest_context": {"note": "y" * 40_000}}
    old_turns = [ChatMessage(role="user", content="z" * 4_000) for _ in range(3)]
    attachment_block = "添付です\n" + "a" * 200
    ctx_json, trimmed, json_truncated, out_attachment, attachment_truncated = (
        fit_chat_payload_to_token_budget(
            payload,
            [*old_turns, ChatMessage(role="user", content="質問")],
            attachment_block=attachment_block,
        )
    )
    assert json_truncated is True
    assert len(ctx_json) < 40_000
    # 古い会話は落ちるが、最後の質問と添付は残る
    assert trimmed == [ChatMessage(role="user", content="質問")]
    assert out_attachment == attachment_block
    assert attachment_truncated is False


def test_fit_chat_payload_truncates_attachment_as_last_resort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        # システムプロンプト + 空の集約 JSON だけで約 1340 トークン。
        # 添付だけが溢れる余地を残した予算にする。
        llm_chat_max_input_tokens=1500,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm_payload.require_settings", lambda: s
    )
    ctx_json, trimmed, _json_truncated, out_attachment, attachment_truncated = (
        fit_chat_payload_to_token_budget(
            {"digest_context": {}},
            [ChatMessage(role="user", content="質問")],
            attachment_block="あ" * 20_000,
        )
    )
    assert attachment_truncated is True
    assert out_attachment is not None
    assert len(out_attachment) < 20_000
    assert ATTACHMENT_TRUNCATION_SUFFIX in out_attachment
    assert trimmed == [ChatMessage(role="user", content="質問")]
    assert estimate_chat_input_tokens(
        merged_context_user_block(ctx_json), trimmed, out_attachment
    ) <= s.llm_chat_max_input_tokens


def test_build_chat_llm_context_reports_attachment_meta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_chat_max_input_tokens=8000,
        llm_anonymization_enabled=False,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm_payload.require_settings", lambda: s
    )
    result = build_chat_llm_context(
        _minimal_ctx(),
        [ChatMessage(role="user", content="ping")],
        period_metrics=None,
        event_time_buckets=None,
        incident_timeline=None,
        extra_vcenter_strings=None,
        attachments=[_text_attachment(body="hello")],
    )
    assert result.attachment_block is not None
    assert "hello" in result.attachment_block
    assert result.images == []
    assert result.meta.attachment_count == 1
    assert result.meta.attachment_text_chars == len(result.attachment_block)
    assert result.meta.attachment_truncated is False


def test_build_chat_llm_context_drops_images_when_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_anonymization_enabled=False,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_llm_payload.require_settings", lambda: s
    )
    image = ChatAttachment(
        kind="image",
        filename="shot.png",
        media_type="image/png",
        data_base64=base64.b64encode(b"0" * 16).decode(),
    )
    result = build_chat_llm_context(
        _minimal_ctx(),
        [ChatMessage(role="user", content="ping")],
        period_metrics=None,
        event_time_buckets=None,
        incident_timeline=None,
        extra_vcenter_strings=None,
        attachments=[image],
        supports_images=False,
    )
    assert result.images == []
    assert result.meta.attachment_count == 0
    assert result.meta.attachments_dropped_reason is not None
