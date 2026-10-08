"""POST /api/chat 統合（タイムラインのメトリクス整形）。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from vcenter_event_assistant.api.schemas import ChatLlmContextMeta
from vcenter_event_assistant.services.chat.chat_event_time_buckets import EventTimeBucketsPayload
from vcenter_event_assistant.services.chat.chat_incident_timeline import IncidentTimelinePayload
from vcenter_event_assistant.services.chat.chat_period_metrics import (
    PeriodMetricBucketPoint,
    PeriodMetricHostSeries,
    PeriodMetricsPayload,
)
from vcenter_event_assistant.services.digest.digest_context import DigestContext
from vcenter_event_assistant.settings import get_settings


def _chat_body(**overrides: object) -> dict:
    base = {
        "from": "2026-03-22T00:00:00Z",
        "to": "2026-03-23T00:00:00Z",
        "messages": [{"role": "user", "content": "質問"}],
        "include_period_metrics_cpu": True,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_post_chat_applies_metric_threshold_and_label_format_in_timeline_entries(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_DIGEST_API_KEY", "sk-test")
    get_settings.cache_clear()
    captured: dict[str, object] = {"entries": None}
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)

    async def _fake_digest_context(*a: object, **k: object) -> DigestContext:
        _ = a
        _ = k
        return DigestContext(
            from_utc=t0,
            to_utc=t1,
            vcenter_count=1,
            total_events=0,
            notable_events_count=0,
            top_notable_event_groups=[],
            top_event_types=[],
            high_cpu_hosts=[],
            high_mem_hosts=[],
        )

    async def _fake_period_metrics(*a: object, **k: object) -> PeriodMetricsPayload:
        _ = a
        _ = k
        return PeriodMetricsPayload(
            bucket_minutes=60,
            from_utc=t0,
            to_utc=t1,
            cpu=[
                PeriodMetricHostSeries(
                    entity_name="esxi-01.prod.local",
                    entity_moid="host-1",
                    metric_key="host.cpu.usage_pct",
                    series=[
                        PeriodMetricBucketPoint(bucket_start_utc=t0, avg=0.0, n=1),
                        PeriodMetricBucketPoint(bucket_start_utc=t0, avg=74.9, n=1),
                        PeriodMetricBucketPoint(bucket_start_utc=t0, avg=75.0, n=1),
                    ],
                )
            ],
        )

    async def _fake_event_buckets(*a: object, **k: object) -> EventTimeBucketsPayload:
        _ = a
        _ = k
        return EventTimeBucketsPayload(
            bucket_minutes=60,
            from_utc=t0,
            to_utc=t1,
            buckets=[],
        )

    def _fake_timeline(*a: object, **k: object) -> IncidentTimelinePayload:
        _ = k
        captured["entries"] = a[0]
        return IncidentTimelinePayload(columns=[])

    async def _fake_run(*a: object, **k: object) -> tuple[str, str | None, object, int | None, float | None]:
        _ = a
        _ = k
        return ("ok", None, None, None, None)

    monkeypatch.setattr("vcenter_event_assistant.services.chat.chat_context_payloads.build_digest_context", _fake_digest_context)
    monkeypatch.setattr("vcenter_event_assistant.services.chat.chat_context_payloads.build_chat_period_metrics", _fake_period_metrics)
    monkeypatch.setattr("vcenter_event_assistant.services.chat.chat_context_payloads.build_chat_event_time_buckets", _fake_event_buckets)
    monkeypatch.setattr("vcenter_event_assistant.services.chat.chat_context_payloads.build_chat_incident_timeline", _fake_timeline)
    monkeypatch.setattr("vcenter_event_assistant.api.routes.chat.run_period_chat", _fake_run)

    r = await client.post("/api/chat", json=_chat_body(metric_threshold_cpu_pct=75))
    assert r.status_code == 200
    entries = captured["entries"]
    assert isinstance(entries, list)
    metric_titles = [entry.title for entry in entries if entry.kind == "metric"]
    assert metric_titles == ["esxi-01 host.cpu.usage_pct: avg=75.00"]


@pytest.mark.asyncio
async def test_post_chat_preview_applies_metric_threshold_and_metric_title_format(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_DIGEST_API_KEY", "sk-test")
    get_settings.cache_clear()
    captured: dict[str, object] = {"entries": None}
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)

    async def _fake_digest_context(*a: object, **k: object) -> DigestContext:
        _ = a
        _ = k
        return DigestContext(
            from_utc=t0,
            to_utc=t1,
            vcenter_count=1,
            total_events=0,
            notable_events_count=0,
            top_notable_event_groups=[],
            top_event_types=[],
            high_cpu_hosts=[],
            high_mem_hosts=[],
        )

    async def _fake_period_metrics(*a: object, **k: object) -> PeriodMetricsPayload:
        _ = a
        _ = k
        return PeriodMetricsPayload(
            bucket_minutes=60,
            from_utc=t0,
            to_utc=t1,
            cpu=[
                PeriodMetricHostSeries(
                    entity_name="esxi-01.prod.local",
                    entity_moid="host-1",
                    metric_key="host.cpu.usage_pct",
                    series=[
                        PeriodMetricBucketPoint(bucket_start_utc=t0, avg=0.0, n=1),
                        PeriodMetricBucketPoint(bucket_start_utc=t0, avg=74.0, n=1),
                        PeriodMetricBucketPoint(bucket_start_utc=t0, avg=75.0, n=1),
                    ],
                )
            ],
        )

    async def _fake_event_buckets(*a: object, **k: object) -> EventTimeBucketsPayload:
        _ = a
        _ = k
        return EventTimeBucketsPayload(
            bucket_minutes=60,
            from_utc=t0,
            to_utc=t1,
            buckets=[],
        )

    def _fake_timeline(*a: object, **k: object) -> IncidentTimelinePayload:
        _ = k
        captured["entries"] = a[0]
        return IncidentTimelinePayload(columns=[])

    def _fake_build_preview(*a: object, **k: object) -> tuple[str, list, ChatLlmContextMeta | None]:
        from vcenter_event_assistant.api.schemas import ChatMessage

        _ = a
        _ = k
        return (
            "preview",
            [ChatMessage(role="user", content="質問")],
            ChatLlmContextMeta(
                json_truncated=False,
                estimated_input_tokens=1,
                max_input_tokens=1000,
                message_turns=1,
            ),
        )

    monkeypatch.setattr("vcenter_event_assistant.services.chat.chat_context_payloads.build_digest_context", _fake_digest_context)
    monkeypatch.setattr("vcenter_event_assistant.services.chat.chat_context_payloads.build_chat_period_metrics", _fake_period_metrics)
    monkeypatch.setattr("vcenter_event_assistant.services.chat.chat_context_payloads.build_chat_event_time_buckets", _fake_event_buckets)
    monkeypatch.setattr("vcenter_event_assistant.services.chat.chat_context_payloads.build_chat_incident_timeline", _fake_timeline)
    monkeypatch.setattr("vcenter_event_assistant.api.routes.chat.build_chat_preview", _fake_build_preview)

    r = await client.post(
        "/api/chat/preview",
        json=_chat_body(metric_threshold_cpu_pct=75),
    )
    assert r.status_code == 200
    entries = captured["entries"]
    assert isinstance(entries, list)
    metric_titles = [entry.title for entry in entries if entry.kind == "metric"]
    assert metric_titles == ["esxi-01 host.cpu.usage_pct: avg=75.00"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("metric_key", "threshold_key", "threshold_value", "include_overrides"),
    [
        (
            "host.mem.usage_pct",
            "metric_threshold_memory_pct",
            70.0,
            {"include_period_metrics_cpu": False, "include_period_metrics_memory": True},
        ),
        (
            "host.disk.usage_pct",
            "metric_threshold_disk_pct",
            80.0,
            {"include_period_metrics_cpu": False, "include_period_metrics_disk_io": True},
        ),
        (
            "host.net.usage_kbps",
            "metric_threshold_network_pct",
            90.0,
            {"include_period_metrics_cpu": False, "include_period_metrics_network_io": True},
        ),
    ],
)
async def test_post_chat_preview_applies_threshold_for_memory_disk_network(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    metric_key: str,
    threshold_key: str,
    threshold_value: float,
    include_overrides: dict[str, object],
) -> None:
    monkeypatch.setenv("LLM_DIGEST_API_KEY", "sk-test")
    get_settings.cache_clear()
    captured: dict[str, object] = {"entries": None}
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)

    async def _fake_digest_context(*a: object, **k: object) -> DigestContext:
        _ = a
        _ = k
        return DigestContext(
            from_utc=t0,
            to_utc=t1,
            vcenter_count=1,
            total_events=0,
            notable_events_count=0,
            top_notable_event_groups=[],
            top_event_types=[],
            high_cpu_hosts=[],
            high_mem_hosts=[],
        )

    async def _fake_period_metrics(*a: object, **k: object) -> PeriodMetricsPayload:
        _ = a
        _ = k
        series = PeriodMetricHostSeries(
            entity_name="esxi-02.prod.local",
            entity_moid="host-2",
            metric_key=metric_key,
            series=[
                PeriodMetricBucketPoint(bucket_start_utc=t0, avg=threshold_value - 0.1, n=1),
                PeriodMetricBucketPoint(bucket_start_utc=t0, avg=threshold_value, n=1),
            ],
        )
        return PeriodMetricsPayload(
            bucket_minutes=60,
            from_utc=t0,
            to_utc=t1,
            cpu=[],
            memory=[series] if metric_key == "host.mem.usage_pct" else None,
            disk=[series] if metric_key == "host.disk.usage_pct" else None,
            network=[series] if metric_key == "host.net.usage_kbps" else None,
        )

    async def _fake_event_buckets(*a: object, **k: object) -> EventTimeBucketsPayload:
        _ = a
        _ = k
        return EventTimeBucketsPayload(
            bucket_minutes=60,
            from_utc=t0,
            to_utc=t1,
            buckets=[],
        )

    def _fake_timeline(*a: object, **k: object) -> IncidentTimelinePayload:
        _ = k
        captured["entries"] = a[0]
        return IncidentTimelinePayload(columns=[])

    def _fake_build_preview(*a: object, **k: object) -> tuple[str, list, ChatLlmContextMeta | None]:
        from vcenter_event_assistant.api.schemas import ChatMessage

        _ = a
        _ = k
        return (
            "preview",
            [ChatMessage(role="user", content="質問")],
            ChatLlmContextMeta(
                json_truncated=False,
                estimated_input_tokens=1,
                max_input_tokens=1000,
                message_turns=1,
            ),
        )

    monkeypatch.setattr("vcenter_event_assistant.services.chat.chat_context_payloads.build_digest_context", _fake_digest_context)
    monkeypatch.setattr("vcenter_event_assistant.services.chat.chat_context_payloads.build_chat_period_metrics", _fake_period_metrics)
    monkeypatch.setattr("vcenter_event_assistant.services.chat.chat_context_payloads.build_chat_event_time_buckets", _fake_event_buckets)
    monkeypatch.setattr("vcenter_event_assistant.services.chat.chat_context_payloads.build_chat_incident_timeline", _fake_timeline)
    monkeypatch.setattr("vcenter_event_assistant.api.routes.chat.build_chat_preview", _fake_build_preview)

    body = _chat_body(**include_overrides, **{threshold_key: threshold_value})
    r = await client.post("/api/chat/preview", json=body)
    assert r.status_code == 200
    entries = captured["entries"]
    assert isinstance(entries, list)
    metric_titles = [entry.title for entry in entries if entry.kind == "metric"]
    assert metric_titles == [f"esxi-02 {metric_key}: avg={threshold_value:.2f}"]
