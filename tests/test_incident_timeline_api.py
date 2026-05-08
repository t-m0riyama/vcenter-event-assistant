"""POST /api/incident-timeline のテスト。"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from vcenter_event_assistant.api.routes import incident_timeline as incident_timeline_route
from vcenter_event_assistant.api.schemas.chat import IncidentTimelineBuildRequest
from vcenter_event_assistant.services.chat_period_metrics import (
    PeriodMetricBucketPoint,
    PeriodMetricHostSeries,
    PeriodMetricsPayload,
)
from vcenter_event_assistant.services.digest_context import DigestContext
from vcenter_event_assistant.services.chat_incident_timeline import IncidentTimelinePayload


def _request_body(**overrides: object) -> dict:
    base = {
        "from": "2026-03-22T00:00:00Z",
        "to": "2026-03-23T00:00:00Z",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_post_incident_timeline_returns_incident_timeline_payload(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/incident-timeline",
        json=_request_body(include_period_metrics_cpu=True),
    )
    assert r.status_code == 200

    data = r.json()
    assert isinstance(data, dict)
    assert set(data.keys()) == {"columns"}
    assert isinstance(data["columns"], list)
    for column in data["columns"]:
        assert {"timestamp_utc", "items", "visible_items", "hidden_count"} <= set(column.keys())
        assert isinstance(column.get("bucket_start_utc"), str)
        assert isinstance(column.get("bucket_end_utc"), str)
        assert isinstance(column["timestamp_utc"], str)
        assert isinstance(column["items"], list)
        assert isinstance(column["visible_items"], list)
        assert isinstance(column["hidden_count"], int)
        assert column["hidden_count"] >= 0
        for item in column["items"]:
            assert {"timestamp_utc", "kind", "title"} <= set(item.keys())
            assert isinstance(item["timestamp_utc"], str)
            assert item["kind"] in {"alert", "event", "metric"}
            assert isinstance(item["title"], str)
            assert item["title"]
            if "trigger_id" in item and item["trigger_id"] is not None:
                assert isinstance(item["trigger_id"], str)
                assert item["trigger_id"]


@pytest.mark.asyncio
async def test_post_incident_timeline_accepts_request_without_messages(
    client: AsyncClient,
) -> None:
    r = await client.post("/api/incident-timeline", json=_request_body())
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_post_incident_timeline_accepts_alert_top_n(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/incident-timeline",
        json=_request_body(alert_top_n=5),
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_post_incident_timeline_rejects_alert_top_n_out_of_range(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/incident-timeline",
        json=_request_body(alert_top_n=0),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_incident_timeline_emits_alert_entries_per_bucket(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 3, 22, 1, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)

    async def _fake_digest_context(*a: object, **k: object) -> DigestContext:
        _ = a
        _ = k
        return DigestContext(
            from_utc=t0,
            to_utc=t2,
            vcenter_count=1,
            total_events=4,
            notable_events_count=4,
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
            to_utc=t2,
            cpu=[],
        )

    async def _fake_event_buckets(*a: object, **k: object) -> SimpleNamespace:
        _ = a
        _ = k
        return SimpleNamespace(
            buckets=[
                SimpleNamespace(
                    bucket_start_utc=t0,
                    total=3,
                    alert_top_types=[
                        SimpleNamespace(
                            event_type="vim.event.HostConnectionLostEvent",
                            count=2,
                            max_notable_score=90,
                        ),
                    ],
                    alert_other_count=1,
                ),
                SimpleNamespace(
                    bucket_start_utc=t1,
                    total=1,
                    alert_top_types=[
                        SimpleNamespace(
                            event_type="vim.event.VmPoweredOffEvent",
                            count=1,
                            max_notable_score=70,
                        ),
                    ],
                    alert_other_count=0,
                ),
            ],
        )

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_context_payloads.build_digest_context",
        _fake_digest_context,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_context_payloads.build_chat_period_metrics",
        _fake_period_metrics,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_context_payloads.build_chat_event_time_buckets",
        _fake_event_buckets,
    )

    r = await client.post(
        "/api/incident-timeline",
        json=_request_body(alert_top_n=3, include_period_metrics_cpu=True),
    )
    assert r.status_code == 200

    alert_items = [
        item
        for column in r.json()["columns"]
        for item in column["items"]
        if item["kind"] == "alert"
    ]
    assert [item["timestamp_utc"] for item in alert_items] == [
        "2026-03-22T01:00:00Z",
        "2026-03-22T00:00:00Z",
        "2026-03-22T00:00:00Z",
    ]
    assert [item["title"] for item in alert_items] == [
        "vim.event.VmPoweredOffEvent (1件, max score=70)",
        "vim.event.HostConnectionLostEvent (2件, max score=90)",
        "その他アラート (1件)",
    ]


@pytest.mark.asyncio
async def test_post_incident_timeline_auto_triggers_are_emitted_as_alerts(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """自動トリガー3種が alert として返ることを固定化する RED テスト。"""
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 3, 22, 2, 0, tzinfo=timezone.utc)
    expected_triggers = {"critical_burst", "multi_signal_overlap", "sustained_breach"}

    async def _fake_digest_context(*a: object, **k: object) -> DigestContext:
        _ = a
        _ = k
        return DigestContext(
            from_utc=t0,
            to_utc=t2,
            vcenter_count=1,
            total_events=14,
            notable_events_count=14,
            top_notable_event_groups=[],
            top_event_types=[],
            high_cpu_hosts=[],
            high_mem_hosts=[],
        )

    cpu_series = [
        PeriodMetricBucketPoint(
            bucket_start_utc=t0.replace(hour=idx),
            avg=value,
            n=1,
        )
        for idx, value in enumerate([96.0, 93.0, 92.0])
    ]

    async def _fake_period_metrics(*a: object, **k: object) -> PeriodMetricsPayload:
        _ = a
        _ = k
        return PeriodMetricsPayload(
            bucket_minutes=60,
            from_utc=t0,
            to_utc=t2,
            cpu=[
                PeriodMetricHostSeries(
                    entity_name="esxi-01",
                    entity_moid="host-1",
                    metric_key="host.cpu.usage_pct",
                    series=cpu_series,
                )
            ],
        )

    async def _fake_event_buckets(*a: object, **k: object) -> SimpleNamespace:
        _ = a
        _ = k
        return SimpleNamespace(
            buckets=[
                SimpleNamespace(
                    bucket_start_utc=t0,
                    total=14,
                    alert_top_types=[],
                    alert_other_count=0,
                ),
            ],
        )

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_context_payloads.build_digest_context",
        _fake_digest_context,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_context_payloads.build_chat_period_metrics",
        _fake_period_metrics,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_context_payloads.build_chat_event_time_buckets",
        _fake_event_buckets,
    )

    r = await client.post(
        "/api/incident-timeline",
        json=_request_body(include_period_metrics_cpu=True),
    )
    assert r.status_code == 200
    emitted_triggers = {
        item["trigger_id"]
        for column in r.json()["columns"]
        for item in column["items"]
        if item["kind"] == "alert"
        and item.get("trigger_id") is not None
    }
    assert emitted_triggers == expected_triggers


@pytest.mark.asyncio
async def test_post_incident_timeline_rejects_messages_field(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/incident-timeline",
        json=_request_body(messages=[{"role": "user", "content": "test"}]),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_incident_timeline_passes_original_request_model(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_build_incident_timeline_payload(
        session: object,
        body: IncidentTimelineBuildRequest,
    ) -> IncidentTimelinePayload:
        assert isinstance(body, IncidentTimelineBuildRequest)
        assert not hasattr(body, "messages")
        return IncidentTimelinePayload(columns=[])

    monkeypatch.setattr(
        incident_timeline_route,
        "build_incident_timeline_payload",
        _fake_build_incident_timeline_payload,
    )

    r = await client.post("/api/incident-timeline", json=_request_body())
    assert r.status_code == 200
    assert r.json() == {"columns": []}


@pytest.mark.asyncio
async def test_post_incident_timeline_returns_400_when_from_equals_to(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/incident-timeline",
        json=_request_body(
            **{
                "from": "2026-03-23T00:00:00Z",
                "to": "2026-03-23T00:00:00Z",
            }
        ),
    )
    assert r.status_code == 400
    assert "前" in r.json().get("detail", "")


@pytest.mark.asyncio
async def test_post_incident_timeline_returns_400_when_from_after_to(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/incident-timeline",
        json=_request_body(
            **{
                "from": "2026-03-24T00:00:00Z",
                "to": "2026-03-23T00:00:00Z",
            }
        ),
    )
    assert r.status_code == 400
    assert "前" in r.json().get("detail", "")
