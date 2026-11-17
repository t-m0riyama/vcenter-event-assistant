"""インシデントタイムラインの集計と、手動スナップショットの API のテスト。

集計の中身は、同じ集計を返すチャットのプレビュー（``POST /api/chat/preview`` の ``incident_timeline``）で確かめる。
旧 ``POST /api/incident-timeline`` は画面から使われていなかったので削除した（Issue #325）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import re

import pytest
from httpx import AsyncClient
from vcenter_event_assistant import main as main_module
from vcenter_event_assistant.api.schemas.chat import IncidentTimelineBuildRequest
from vcenter_event_assistant.db.models import EventRecord, IncidentTimelineManualSnapshot, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.chat.chat_period_metrics import (
    PeriodMetricBucketPoint,
    PeriodMetricHostSeries,
    PeriodMetricsPayload,
)
from vcenter_event_assistant.services.digest.digest_context import DigestContext

PREVIEW_URL = "/api/chat/preview"


@pytest.fixture
def stub_preview_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """プレビューのプロンプト組み立てを差し替える。

    集計関数を ``SimpleNamespace`` で差し替えるテストでは、プロンプト用の JSON 化ができない。
    応答の ``incident_timeline`` は集計結果をそのまま返すので、プロンプトを組み立てなくても中身を確かめられる。
    """
    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.chat.build_chat_preview",
        lambda *a, **k: ("", [], None),
    )


def _preview_body(**overrides: object) -> dict:
    base = {
        "from": "2026-03-22T00:00:00Z",
        "to": "2026-03-23T00:00:00Z",
        "messages": [{"role": "user", "content": "質問"}],
    }
    base.update(overrides)
    return base


def _manual_snapshot_request_body(**overrides: object) -> dict:
    base = {
        "from": "2026-03-22T00:00:00Z",
        "to": "2026-03-23T00:00:00Z",
        "timestamp_utc": "2026-03-22T01:23:45Z",
        "operator_note": "初動調査のため手動スナップショットを保存",
        "build_request_payload": {
            "from": "2026-03-22T00:00:00Z",
            "to": "2026-03-23T00:00:00Z",
            "vcenter_id": "550e8400-e29b-41d4-a716-446655440000",
            "include_period_metrics_cpu": True,
            "include_period_metrics_memory": True,
            "metric_threshold_cpu_pct": 90,
            "metric_threshold_memory_pct": 88,
            "alert_top_n": 11,
        },
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
@pytest.mark.parametrize(("with_frontend_dist", "expected_status"), [(True, 405), (False, 404)])
async def test_legacy_post_incident_timeline_is_removed(
    open_client,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    with_frontend_dist: bool,
    expected_status: int,
) -> None:
    """旧 POST /api/incident-timeline は無い（Issue #325）。

    画面のビルド（frontend/dist）があると SPA 用の GET の受け口がこのパスにも一致するので 405、無いと 404 になる。
    手元と CI で結果が変わらないよう、dist の有無はテストの中で決める。
    """
    dist = tmp_path / "dist"
    if with_frontend_dist:
        dist.mkdir()
        (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(main_module, "FRONTEND_DIST", dist)
    async with open_client("admin") as client:
        r = await client.post(
            "/api/incident-timeline",
            json={"from": "2026-03-22T00:00:00Z", "to": "2026-03-23T00:00:00Z"},
        )
    assert r.status_code == expected_status


@pytest.mark.asyncio
async def test_chat_preview_returns_incident_timeline_payload(
    client: AsyncClient,
) -> None:
    r = await client.post(
        PREVIEW_URL,
        json=_preview_body(include_period_metrics_cpu=True),
    )
    assert r.status_code == 200

    data = r.json()["incident_timeline"]
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
            allowed_keys = {"timestamp_utc", "kind", "title", "trigger_id"}
            assert {"timestamp_utc", "kind", "title"} <= set(item.keys())
            assert set(item.keys()) <= allowed_keys
            assert isinstance(item["timestamp_utc"], str)
            assert item["kind"] in {"alert", "event", "metric"}
            assert isinstance(item["title"], str)
            assert item["title"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("stub_preview_prompt")
async def test_chat_preview_emits_alert_entries_per_bucket(
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
        "vcenter_event_assistant.services.chat.chat_context_payloads.build_digest_context",
        _fake_digest_context,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_context_payloads.build_chat_period_metrics",
        _fake_period_metrics,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_context_payloads.build_chat_event_time_buckets",
        _fake_event_buckets,
    )

    r = await client.post(
        PREVIEW_URL,
        json=_preview_body(include_period_metrics_cpu=True),
    )
    assert r.status_code == 200

    alert_items = [
        item
        for column in r.json()["incident_timeline"]["columns"]
        for item in column["items"]
        if item["kind"] == "alert"
    ]
    assert len(alert_items) == 3
    timestamp_counts = {
        ts: [item["timestamp_utc"] for item in alert_items].count(ts)
        for ts in {item["timestamp_utc"] for item in alert_items}
    }
    assert timestamp_counts == {
        "2026-03-22T00:00:00Z": 2,
        "2026-03-22T01:00:00Z": 1,
    }
    alert_title_tokens = {item["title"].split(" (", 1)[0] for item in alert_items}
    assert {
        "vim.event.HostConnectionLostEvent",
        "vim.event.VmPoweredOffEvent",
        "その他アラート",
    } <= alert_title_tokens


@pytest.mark.asyncio
async def test_chat_preview_shows_top_three_alert_types_per_bucket(
    client: AsyncClient,
) -> None:
    """差し替えなしで、1 バケットのアラートは既定の上位 3 種別と「その他」で出る（件数は指定できない）。"""
    vid = uuid.uuid4()
    base = datetime(2026, 3, 22, 10, 0, tzinfo=timezone.utc)
    async with session_scope() as session:
        session.add(
            VCenter(
                id=vid,
                name="vc",
                host="h",
                port=443,
                username="u",
                password="p",
                is_enabled=True,
            )
        )
        # 同じ 1 時間バケットに 5 種別（notable_score は種別ごとに異なる）。
        for i, (event_type, score) in enumerate(
            [
                ("vim.Alert-A", 90),
                ("vim.Alert-B", 80),
                ("vim.Alert-C", 70),
                ("vim.Alert-D", 60),
                ("vim.Alert-E", 50),
            ],
        ):
            session.add(
                EventRecord(
                    vcenter_id=vid,
                    occurred_at=base + timedelta(minutes=i),
                    event_type=event_type,
                    message="",
                    vmware_key=2000 + i,
                    notable_score=score,
                ),
            )

    r = await client.post(
        PREVIEW_URL,
        json=_preview_body(include_period_metrics_cpu=True),
    )
    assert r.status_code == 200
    alert_items = [
        item
        for column in r.json()["incident_timeline"]["columns"]
        for item in column["items"]
        if item["kind"] == "alert" and item["timestamp_utc"] == "2026-03-22T10:00:00Z"
    ]
    # 種別行は「種別名 (N件, max score=…)」、その他行は「その他アラート (N件)」。
    titles = [
        item["title"] if item["title"].startswith("その他") else item["title"].split(" (", 1)[0]
        for item in alert_items
    ]
    assert sorted(titles) == sorted(["vim.Alert-A", "vim.Alert-B", "vim.Alert-C", "その他アラート (2件)"])


@pytest.mark.asyncio
@pytest.mark.usefixtures("stub_preview_prompt")
async def test_chat_preview_auto_triggers_are_emitted_as_alerts(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """自動トリガー3種が alert として返ることを固定化する RED テスト。"""
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 3, 22, 2, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 3, 22, 3, 0, tzinfo=timezone.utc)
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
        PeriodMetricBucketPoint(bucket_start_utc=t0.replace(hour=idx), avg=value, n=1)
        for idx, value in enumerate([96.0, 93.0, 92.0])
    ]

    async def _fake_period_metrics(*a: object, **k: object) -> PeriodMetricsPayload:
        _ = a
        _ = k
        return PeriodMetricsPayload(
            bucket_minutes=60,
            from_utc=t0,
            to_utc=t3,
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
                    alert_top_types=[
                        SimpleNamespace(
                            event_type="vim.event.HostConnectionLostEvent",
                            count=5,
                            max_notable_score=95,
                        ),
                        SimpleNamespace(
                            event_type="vim.event.DatastoreFileDeletedEvent",
                            count=5,
                            max_notable_score=91,
                        ),
                        SimpleNamespace(
                            event_type="vim.event.VmPoweredOffEvent",
                            count=4,
                            max_notable_score=90,
                        ),
                    ],
                    alert_other_count=0,
                ),
            ],
        )

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_context_payloads.build_digest_context",
        _fake_digest_context,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_context_payloads.build_chat_period_metrics",
        _fake_period_metrics,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_context_payloads.build_chat_event_time_buckets",
        _fake_event_buckets,
    )

    r = await client.post(
        PREVIEW_URL,
        json=_preview_body(include_period_metrics_cpu=True),
    )
    assert r.status_code == 200
    alert_items = [
        item
        for column in r.json()["incident_timeline"]["columns"]
        for item in column["items"]
        if item["kind"] == "alert"
    ]
    assert alert_items
    # 前提確認: フィクスチャは「高notableイベント多発 + 高CPU持続」を発生させる
    # （GREENではこの入力から trigger_id が構造化フィールドとして返ることを期待）
    assert len(alert_items) >= 3
    emitted_trigger_ids = {item.get("trigger_id") for item in alert_items if item.get("trigger_id") is not None}
    assert all(isinstance(trigger_id, str) for trigger_id in emitted_trigger_ids)
    assert all(re.fullmatch(r"[a-z]+(?:_[a-z]+)*", trigger_id) for trigger_id in emitted_trigger_ids)
    assert emitted_trigger_ids == expected_triggers


@pytest.mark.asyncio
@pytest.mark.usefixtures("stub_preview_prompt")
async def test_chat_preview_does_not_persist_auto_trigger_snapshots(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 3, 22, 2, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 3, 22, 3, 0, tzinfo=timezone.utc)

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
        PeriodMetricBucketPoint(bucket_start_utc=t0.replace(hour=idx), avg=value, n=1)
        for idx, value in enumerate([96.0, 93.0, 92.0])
    ]

    async def _fake_period_metrics(*a: object, **k: object) -> PeriodMetricsPayload:
        _ = a
        _ = k
        return PeriodMetricsPayload(
            bucket_minutes=60,
            from_utc=t0,
            to_utc=t3,
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
        "vcenter_event_assistant.services.chat.chat_context_payloads.build_digest_context",
        _fake_digest_context,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_context_payloads.build_chat_period_metrics",
        _fake_period_metrics,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_context_payloads.build_chat_event_time_buckets",
        _fake_event_buckets,
    )

    r = await client.post(
        PREVIEW_URL,
        json=_preview_body(include_period_metrics_cpu=True),
    )
    assert r.status_code == 200

    list_r = await client.get(
        "/api/incident-timeline/snapshots/manual",
        params={"limit": 20, "offset": 0},
    )
    assert list_r.status_code == 200
    items = list_r.json()["items"]
    auto_items = [item for item in items if item.get("snapshot_kind") == "auto"]
    assert auto_items == []


@pytest.mark.asyncio
async def test_post_manual_snapshot_rejects_build_request_payload_when_from_equals_to(
    client: AsyncClient,
) -> None:
    """build_request_payload（IncidentTimelineBuildRequest）の from/to の検証。外側の from/to は正しい。"""
    body = _manual_snapshot_request_body()
    body["build_request_payload"].update({"from": "2026-03-23T00:00:00Z", "to": "2026-03-23T00:00:00Z"})
    r = await client.post("/api/incident-timeline/snapshots/manual", json=body)
    assert r.status_code == 422
    assert all("build_request_payload" in error["loc"] for error in r.json()["detail"])
    detail = str(r.json().get("detail", ""))
    assert "from" in detail.lower() or "前" in detail


@pytest.mark.asyncio
async def test_post_manual_snapshot_rejects_build_request_payload_when_from_after_to(
    client: AsyncClient,
) -> None:
    body = _manual_snapshot_request_body()
    body["build_request_payload"].update({"from": "2026-03-24T00:00:00Z", "to": "2026-03-23T00:00:00Z"})
    r = await client.post("/api/incident-timeline/snapshots/manual", json=body)
    assert r.status_code == 422
    assert all("build_request_payload" in error["loc"] for error in r.json()["detail"])
    detail = str(r.json().get("detail", ""))
    assert "from" in detail.lower() or "前" in detail


@pytest.mark.asyncio
async def test_post_manual_snapshot_creates_snapshot_when_operator_note_present(
    client: AsyncClient,
) -> None:
    request_body = _manual_snapshot_request_body()
    r = await client.post(
        "/api/incident-timeline/snapshots/manual",
        json=request_body,
    )
    assert r.status_code == 201
    data = r.json()
    assert isinstance(data.get("snapshot_id"), str)
    assert data.get("operator_note") == "初動調査のため手動スナップショットを保存"
    assert data.get("timestamp_utc") == "2026-03-22T01:23:45Z"
    assert isinstance(data.get("build_request_payload"), dict)
    assert data.get("snapshot_kind") == "manual"
    assert data.get("trigger_id") is None
    build_request = IncidentTimelineBuildRequest.model_validate(data["build_request_payload"])
    assert build_request.from_time == datetime.fromisoformat(request_body["from"].replace("Z", "+00:00"))
    assert build_request.to_time == datetime.fromisoformat(request_body["to"].replace("Z", "+00:00"))
    assert build_request.alert_top_n == 11
    assert build_request.include_period_metrics_cpu is True


@pytest.mark.asyncio
async def test_post_manual_snapshot_persists_build_request_payload(
    client: AsyncClient,
) -> None:
    request_body = _manual_snapshot_request_body()

    r = await client.post(
        "/api/incident-timeline/snapshots/manual",
        json=request_body,
    )
    assert r.status_code == 201
    snapshot_id = uuid.UUID(r.json()["snapshot_id"])

    async with session_scope() as session:
        snapshot = await session.get(IncidentTimelineManualSnapshot, snapshot_id)
        assert snapshot is not None
        build_request = IncidentTimelineBuildRequest.model_validate(snapshot.build_request_payload)
        assert build_request.from_time == datetime.fromisoformat(request_body["from"].replace("Z", "+00:00"))
        assert build_request.to_time == datetime.fromisoformat(request_body["to"].replace("Z", "+00:00"))
        assert build_request.alert_top_n == 11
        assert build_request.metric_threshold_cpu_pct == 90
        assert "timestamp_utc" not in snapshot.build_request_payload
        assert "operator_note" not in snapshot.build_request_payload


@pytest.mark.asyncio
async def test_post_manual_snapshot_rejects_missing_operator_note(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/incident-timeline/snapshots/manual",
        json={},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_manual_snapshot_rejects_blank_operator_note(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/incident-timeline/snapshots/manual",
        json=_manual_snapshot_request_body(operator_note="   "),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_manual_snapshot_rejects_invalid_time_range(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/incident-timeline/snapshots/manual",
        json=_manual_snapshot_request_body(
            **{
                "from": "2026-03-23T00:00:00Z",
                "to": "2026-03-23T00:00:00Z",
            }
        ),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_manual_snapshots_returns_paginated_list_with_limit_offset(
    client: AsyncClient,
) -> None:
    await client.post(
        "/api/incident-timeline/snapshots/manual",
        json=_manual_snapshot_request_body(
            timestamp_utc="2026-03-22T01:23:45Z",
            operator_note="監査確認-1",
        ),
    )
    await client.post(
        "/api/incident-timeline/snapshots/manual",
        json=_manual_snapshot_request_body(
            timestamp_utc="2026-03-22T01:24:45Z",
            operator_note="監査確認-2",
        ),
    )

    r = await client.get(
        "/api/incident-timeline/snapshots/manual",
        params={"limit": 1, "offset": 0},
    )
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == {"items", "total", "limit", "offset"}
    assert data["limit"] == 1
    assert data["offset"] == 0
    assert isinstance(data["total"], int)
    assert data["total"] >= 2
    assert isinstance(data["items"], list)
    assert len(data["items"]) == 1
    assert {
        "snapshot_id",
        "from",
        "to",
        "operator_note",
        "timestamp_utc",
        "build_request_payload",
        "snapshot_kind",
        "trigger_id",
        "trigger_evidence",
        "graph_context",
    } <= set(data["items"][0].keys())
    assert isinstance(data["items"][0]["timestamp_utc"], str)
    assert data["items"][0]["timestamp_utc"].endswith("Z")
    assert isinstance(data["items"][0]["from"], str)
    assert isinstance(data["items"][0]["to"], str)
    assert data["items"][0]["from"].endswith("Z")
    assert data["items"][0]["to"].endswith("Z")
    build_request = IncidentTimelineBuildRequest.model_validate(data["items"][0]["build_request_payload"])
    assert build_request.from_time == datetime.fromisoformat(data["items"][0]["from"].replace("Z", "+00:00"))
    assert build_request.to_time == datetime.fromisoformat(data["items"][0]["to"].replace("Z", "+00:00"))


@pytest.mark.asyncio
async def test_post_manual_snapshot_persists_graph_context_round_trip(
    client: AsyncClient,
) -> None:
    vid = "550e8400-e29b-41d4-a716-446655440000"
    graph_context = {
        "metric_key": "host.cpu.usage_pct",
        "chart_event_type": "VmPoweredOnEvent",
        "vcenter_id": vid,
        "marker_timestamp_utc": "2026-03-22T06:30:00Z",
        "captured_range": {"from": "2026-03-22T00:00:00Z", "to": "2026-03-23T00:00:00Z"},
    }
    request_body = _manual_snapshot_request_body(
        operator_note="graph ctx 付き保存",
        graph_context=graph_context,
    )
    r = await client.post(
        "/api/incident-timeline/snapshots/manual",
        json=request_body,
    )
    assert r.status_code == 201
    data = r.json()
    assert data.get("graph_context") == graph_context

    list_r = await client.get(
        "/api/incident-timeline/snapshots/manual",
        params={"limit": 20, "offset": 0},
    )
    assert list_r.status_code == 200
    items = list_r.json()["items"]
    match = next((x for x in items if x.get("operator_note") == "graph ctx 付き保存"), None)
    assert match is not None
    assert match.get("graph_context") == graph_context


@pytest.mark.asyncio
async def test_post_manual_snapshot_rejects_invalid_graph_context(
    client: AsyncClient,
) -> None:
    request_body = _manual_snapshot_request_body(
        operator_note="invalid graph",
        graph_context={"metric_key": "x" * 513},
    )
    r = await client.post(
        "/api/incident-timeline/snapshots/manual",
        json=request_body,
    )
    assert r.status_code == 422
