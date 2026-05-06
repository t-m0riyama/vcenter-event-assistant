"""POST /api/chat/preview のテスト。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from vcenter_event_assistant.api.schemas import ChatLlmContextMeta, HighCpuHostRow
from vcenter_event_assistant.services.chat_event_time_buckets import EventTimeBucketRow, EventTimeBucketsPayload
from vcenter_event_assistant.services.chat_incident_timeline import IncidentTimelinePayload
from vcenter_event_assistant.services.chat_period_metrics import (
    PeriodMetricBucketPoint,
    PeriodMetricHostSeries,
    PeriodMetricsPayload,
)
from vcenter_event_assistant.services.digest_context import DigestContext, DigestNotableEventGroup
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

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.build_chat_preview",
        _fake_build,
    )

    resp = await client.post("/api/chat/preview", json=_chat_body())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "context_block" in data
    assert "conversation" in data
    assert "llm_context" in data
    assert data["context_block"] == "プレビュー用コンテキストブロック"


@pytest.mark.asyncio
async def test_post_chat_preview_builds_incident_timeline_and_passes_to_preview_builder(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_DIGEST_API_KEY", "sk-test")
    get_settings.cache_clear()
    captured: dict[str, object] = {"entries": None}
    called: dict[str, int] = {"metrics": 0, "events": 0}

    async def _fake_digest_context(*a: object, **k: object) -> DigestContext:
        _ = a
        _ = k
        t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
        return DigestContext(
            from_utc=t0,
            to_utc=t1,
            vcenter_count=1,
            total_events=1,
            notable_events_count=1,
            top_notable_event_groups=[
                DigestNotableEventGroup(
                    event_type="vim.event.HostConnectionLostEvent",
                    occurrence_count=1,
                    notable_score=80,
                    occurred_at_first=t0,
                    occurred_at_last=t0,
                    entity_name="esxi-01",
                    message="lost",
                )
            ],
            top_event_types=[],
            high_cpu_hosts=[
                HighCpuHostRow(
                    vcenter_id="vc-1",
                    vcenter_label="vc1",
                    entity_name="esxi-01",
                    entity_moid="host-1",
                    value=72.0,
                    sampled_at=t0,
                )
            ],
            high_mem_hosts=[],
        )

    def _fake_timeline(*a: object, **k: object) -> IncidentTimelinePayload:
        captured["entries"] = a[0] if a else None
        _ = k
        return IncidentTimelinePayload(columns=[])

    async def _fake_event_buckets(*a: object, **k: object) -> EventTimeBucketsPayload:
        _ = a
        _ = k
        called["events"] += 1
        t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
        return EventTimeBucketsPayload(
            bucket_minutes=60,
            from_utc=t0,
            to_utc=t1,
            buckets=[
                EventTimeBucketRow(
                    bucket_start_utc=t0,
                    total=2,
                    by_type={"vim.event.HostConnectedEvent": 2},
                )
            ],
        )

    async def _fake_period_metrics(*a: object, **k: object) -> PeriodMetricsPayload:
        _ = a
        _ = k
        called["metrics"] += 1
        t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
        return PeriodMetricsPayload(
            bucket_minutes=60,
            from_utc=t0,
            to_utc=t1,
            cpu=[
                PeriodMetricHostSeries(
                    entity_name="esxi-01",
                    entity_moid="host-1",
                    metric_key="host.cpu.usage_pct",
                    series=[PeriodMetricBucketPoint(bucket_start_utc=t0, avg=35.0, n=1)],
                )
            ],
        )

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.build_digest_context",
        _fake_digest_context,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.build_chat_event_time_buckets",
        _fake_event_buckets,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.build_chat_period_metrics",
        _fake_period_metrics,
    )

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.build_chat_incident_timeline",
        _fake_timeline,
    )

    def _fake_build(*a: object, **k: object) -> tuple[str, list, ChatLlmContextMeta | None]:
        from vcenter_event_assistant.api.schemas import ChatMessage

        captured["incident_timeline"] = k.get("incident_timeline")
        return (
            "プレビュー用コンテキストブロック",
            [ChatMessage(role="user", content="質問")],
            ChatLlmContextMeta(
                json_truncated=False,
                estimated_input_tokens=100,
                max_input_tokens=1000,
                message_turns=1,
            ),
        )

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.build_chat_preview",
        _fake_build,
    )

    resp = await client.post("/api/chat/preview", json=_chat_body())
    assert resp.status_code == 200
    assert called == {"metrics": 0, "events": 0}
    assert captured["incident_timeline"] is not None
    entries = captured["entries"]
    assert isinstance(entries, list)
    kinds = {entry.kind for entry in entries}
    assert {"alert", "event", "metric"} <= kinds


@pytest.mark.asyncio
async def test_post_chat_preview_cpu_toggle_only_keeps_cpu_metrics_in_timeline(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_DIGEST_API_KEY", "sk-test")
    get_settings.cache_clear()
    captured: dict[str, object] = {"entries": None, "metric_kwargs": None}

    async def _fake_digest_context(*a: object, **k: object) -> DigestContext:
        _ = a
        _ = k
        t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
        return DigestContext(
            from_utc=t0,
            to_utc=t1,
            vcenter_count=1,
            total_events=1,
            notable_events_count=1,
            top_notable_event_groups=[
                DigestNotableEventGroup(
                    event_type="vim.event.HostConnectionLostEvent",
                    occurrence_count=1,
                    notable_score=80,
                    occurred_at_first=t0,
                    occurred_at_last=t0,
                    entity_name="esxi-01",
                    message="lost",
                )
            ],
            top_event_types=[],
            high_cpu_hosts=[],
            high_mem_hosts=[],
        )

    async def _fake_event_buckets(*a: object, **k: object) -> EventTimeBucketsPayload:
        _ = a
        _ = k
        t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
        return EventTimeBucketsPayload(
            bucket_minutes=60,
            from_utc=t0,
            to_utc=t1,
            buckets=[
                EventTimeBucketRow(
                    bucket_start_utc=t0,
                    total=1,
                    by_type={"vim.event.HostConnectedEvent": 1},
                )
            ],
        )

    async def _fake_period_metrics(*a: object, **k: object) -> PeriodMetricsPayload:
        _ = a
        captured["metric_kwargs"] = k
        t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
        cpu_series = PeriodMetricHostSeries(
            entity_name="esxi-01",
            entity_moid="host-1",
            metric_key="host.cpu.usage_pct",
            series=[PeriodMetricBucketPoint(bucket_start_utc=t0, avg=35.0, n=1)],
        )
        mem_series = PeriodMetricHostSeries(
            entity_name="esxi-01",
            entity_moid="host-1",
            metric_key="host.mem.usage_pct",
            series=[PeriodMetricBucketPoint(bucket_start_utc=t0, avg=82.0, n=1)],
        )
        return PeriodMetricsPayload(
            bucket_minutes=60,
            from_utc=t0,
            to_utc=t1,
            cpu=[cpu_series],
            memory=[mem_series],
        )

    def _fake_timeline(*a: object, **k: object) -> IncidentTimelinePayload:
        _ = k
        captured["entries"] = a[0] if a else None
        return IncidentTimelinePayload(columns=[])

    def _fake_build(*a: object, **k: object) -> tuple[str, list, ChatLlmContextMeta | None]:
        from vcenter_event_assistant.api.schemas import ChatMessage

        _ = a
        _ = k
        return (
            "プレビュー用コンテキストブロック",
            [ChatMessage(role="user", content="質問")],
            ChatLlmContextMeta(
                json_truncated=False,
                estimated_input_tokens=100,
                max_input_tokens=1000,
                message_turns=1,
            ),
        )

    monkeypatch.setattr("vcenter_event_assistant.api.routes.chat.build_digest_context", _fake_digest_context)
    monkeypatch.setattr("vcenter_event_assistant.api.routes.chat.build_chat_event_time_buckets", _fake_event_buckets)
    monkeypatch.setattr("vcenter_event_assistant.api.routes.chat.build_chat_period_metrics", _fake_period_metrics)
    monkeypatch.setattr("vcenter_event_assistant.api.routes.chat.build_chat_incident_timeline", _fake_timeline)
    monkeypatch.setattr("vcenter_event_assistant.api.routes.chat.build_chat_preview", _fake_build)

    resp = await client.post(
        "/api/chat/preview",
        json={**_chat_body(), "include_period_metrics_cpu": True},
    )
    assert resp.status_code == 200
    metric_kwargs = captured["metric_kwargs"]
    assert isinstance(metric_kwargs, dict)
    assert metric_kwargs["include_cpu"] is True
    assert metric_kwargs["include_memory"] is False
    assert metric_kwargs["include_disk_io"] is False
    assert metric_kwargs["include_network_io"] is False

    entries = captured["entries"]
    assert isinstance(entries, list)
    metric_titles = [entry.title for entry in entries if entry.kind == "metric"]
    assert any(title.startswith("host.cpu.usage_pct:") for title in metric_titles)
    assert not any(title.startswith("host.mem.usage_pct:") for title in metric_titles)
