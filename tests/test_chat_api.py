"""POST /api/chat のテスト。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from vcenter_event_assistant.api.schemas import ChatLlmContextMeta, HighCpuHostRow
from vcenter_event_assistant.services.chat_event_time_buckets import EventTimeBucketsPayload
from vcenter_event_assistant.services.chat_event_time_buckets import EventTimeBucketRow
from vcenter_event_assistant.services.chat_incident_timeline import IncidentTimelinePayload
from vcenter_event_assistant.services.chat_period_metrics import PeriodMetricBucketPoint
from vcenter_event_assistant.services.chat_period_metrics import PeriodMetricHostSeries
from vcenter_event_assistant.services.chat_period_metrics import PeriodMetricsPayload
from vcenter_event_assistant.services.digest_context import DigestContext
from vcenter_event_assistant.services.digest_context import DigestNotableEventGroup
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
@pytest.mark.parametrize(
    ("threshold_key", "invalid_value"),
    [
        ("metric_threshold_cpu_pct", -1),
        ("metric_threshold_memory_pct", 101),
        ("metric_threshold_disk_pct", -0.1),
        ("metric_threshold_network_pct", 100.1),
    ],
)
async def test_post_chat_returns_422_when_metric_threshold_out_of_range(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    threshold_key: str,
    invalid_value: float,
) -> None:
    monkeypatch.setenv("LLM_DIGEST_API_KEY", "sk-test")
    get_settings.cache_clear()

    async def _fake_run(*a: object, **k: object) -> tuple[str, str | None, object, int | None, float | None]:
        _ = a
        _ = k
        return ("ok", None, None, None, None)

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.run_period_chat",
        _fake_run,
    )

    r = await client.post(
        "/api/chat",
        json=_chat_body(**{threshold_key: invalid_value}),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_chat_accepts_metric_thresholds_in_range(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_DIGEST_API_KEY", "sk-test")
    get_settings.cache_clear()

    async def _fake_run(*a: object, **k: object) -> tuple[str, str | None, object, int | None, float | None]:
        _ = a
        _ = k
        return ("ok", None, None, None, None)

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.run_period_chat",
        _fake_run,
    )

    r = await client.post(
        "/api/chat",
        json=_chat_body(
            metric_threshold_cpu_pct=0,
            metric_threshold_memory_pct=25.5,
            metric_threshold_disk_pct=80,
            metric_threshold_network_pct=100,
        ),
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_post_chat_returns_assistant_content_when_llm_succeeds(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_DIGEST_API_KEY", "sk-test")
    get_settings.cache_clear()

    async def _fake_run(*a: object, **k: object) -> tuple[str, str | None, object, int | None, float | None]:
        return ("回答テキスト", None, None, 1500, 15.5)

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

    async def _fake_run(*a: object, **k: object) -> tuple[str, str | None, ChatLlmContextMeta, int | None, float | None]:
        return (
            "回答",
            None,
            ChatLlmContextMeta(
                json_truncated=True,
                estimated_input_tokens=4000,
                max_input_tokens=32000,
                message_turns=1,
            ),
            120,
            20.0,
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

    async def _fake_fail(*a: object, **k: object) -> tuple[str, str | None, object, int | None, float | None]:
        return ("", "何か失敗", None, None, None)

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

    async def _fake_run(*a: object, **k: object) -> tuple[str, str | None, object, int | None, float | None]:
        return ("ok", None, None, None, None)

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
async def test_post_chat_sets_period_payloads_none_when_all_toggles_false(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_DIGEST_API_KEY", "sk-test")
    get_settings.cache_clear()
    called: dict[str, int] = {"metrics": 0, "events": 0}
    captured: dict[str, object] = {}

    async def _fake_metrics(*a: object, **k: object) -> PeriodMetricsPayload:
        _ = a
        _ = k
        called["metrics"] += 1
        return PeriodMetricsPayload(
            bucket_minutes=60,
            from_utc=datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc),
            to_utc=datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc),
            cpu=[],
        )

    async def _fake_buckets(*a: object, **k: object) -> EventTimeBucketsPayload:
        _ = a
        _ = k
        called["events"] += 1
        return EventTimeBucketsPayload(
            bucket_minutes=60,
            from_utc=datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc),
            to_utc=datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc),
            buckets=[],
        )

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.build_chat_period_metrics",
        _fake_metrics,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.build_chat_event_time_buckets",
        _fake_buckets,
    )

    async def _fake_run(*a: object, **k: object) -> tuple[str, str | None, object, int | None, float | None]:
        captured["period_metrics"] = k.get("period_metrics")
        captured["event_time_buckets"] = k.get("event_time_buckets")
        return ("ok", None, None, None, None)

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.run_period_chat",
        _fake_run,
    )

    r = await client.post("/api/chat", json=_chat_body())
    assert r.status_code == 200
    assert called == {"metrics": 0, "events": 0}
    assert captured["period_metrics"] is None
    assert captured["event_time_buckets"] is None


@pytest.mark.asyncio
async def test_post_chat_builds_incident_timeline_and_passes_to_run_period_chat(
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
                    value=83.5,
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
                    total=3,
                    by_type={"vim.event.HostConnectedEvent": 3},
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
                    series=[PeriodMetricBucketPoint(bucket_start_utc=t0, avg=42.0, n=1)],
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

    async def _fake_run(*a: object, **k: object) -> tuple[str, str | None, object, int | None, float | None]:
        captured["incident_timeline"] = k.get("incident_timeline")
        return ("ok", None, None, None, None)

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.run_period_chat",
        _fake_run,
    )

    r = await client.post("/api/chat", json=_chat_body())
    assert r.status_code == 200
    assert called == {"metrics": 0, "events": 0}
    assert captured["incident_timeline"] is not None
    entries = captured["entries"]
    assert isinstance(entries, list)
    kinds = {entry.kind for entry in entries}
    assert {"alert", "event", "metric"} <= kinds
