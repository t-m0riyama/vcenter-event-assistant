"""POST /api/incident-timeline/view のテスト。

イベントとアラートを個々の出来事として返し、俯瞰・ハイライトを付ける API の振る舞いを確かめる。
level の決め方:
- event: notable_score 80 以上 critical / 60 以上 error / 40 以上 warning / それ未満 info。
  ただし severity が error 相当なら少なくとも error、warning 相当なら少なくとも warning。
- alert: alert_level をそのまま使う。
"""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from vcenter_event_assistant.api.schemas.incident_timeline_view import IncidentTimelineViewRequest
from vcenter_event_assistant.db.models import AlertHistory, AlertRule, EventRecord, MetricSample, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alerting.alert_eval_common import metric_context_key
from vcenter_event_assistant.services.chat.aggregation_limiter import aggregation_slot
from vcenter_event_assistant.settings_binding import require_settings

T0 = datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
URL = "/api/incident-timeline/view"
_keys = itertools.count(1)


def _body(**overrides: object) -> dict:
    base: dict[str, object] = {"from": "2026-03-22T00:00:00Z", "to": "2026-03-22T02:00:00Z"}
    base.update(overrides)
    return base


def _at(minute: float) -> datetime:
    return T0 + timedelta(minutes=minute)


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def _vcenter(name: str = "vc-1") -> uuid.UUID:
    vid = uuid.uuid4()
    async with session_scope() as session:
        session.add(VCenter(id=vid, name=name, host="h", port=443, username="u", password="p"))
    return vid


async def _events(vid: uuid.UUID, *specs: tuple) -> list[int]:
    """spec は (分, event_type, entity_name, score) か、それに dict（追加フィールド）を足したもの。"""
    ids: list[int] = []
    async with session_scope() as session:
        rows = []
        for spec in specs:
            minute, event_type, entity, score, *rest = spec
            extra = rest[0] if rest else {}
            row = EventRecord(
                vcenter_id=vid,
                occurred_at=_at(minute),
                event_type=event_type,
                message=extra.pop("message", f"{event_type} on {entity}"),
                entity_name=entity,
                entity_type=extra.pop("entity_type", "HostSystem"),
                notable_score=score,
                vmware_key=next(_keys),
                **extra,
            )
            session.add(row)
            rows.append(row)
        await session.flush()
        ids = [r.id for r in rows]
    return ids


async def _post(client: AsyncClient, **overrides: object) -> dict:
    r = await client.post(URL, json=_body(**overrides))
    assert r.status_code == 200, r.text
    return r.json()


# --- スキーマ検証（サービス未実装でも通る） ---------------------------------------------


def test_request_defaults() -> None:
    req = IncidentTimelineViewRequest.model_validate({"from": "2026-03-22T00:00:00Z", "to": "2026-03-22T01:00:00Z"})
    assert req.min_score == 1
    assert req.sources == ["event", "alert", "metric", "log"]
    assert (
        req.metric_threshold_cpu_pct,
        req.metric_threshold_memory_pct,
        req.metric_threshold_disk_pct,
        req.metric_threshold_network_pct,
    ) == (80, 85, 75, 75)
    assert req.item_limit == 500
    assert req.entity is None and req.anchor_time is None


def test_request_normalizes_entity_and_sources() -> None:
    req = IncidentTimelineViewRequest.model_validate(
        _body(entity="  esx01  ", sources=["alert", "event", "alert"], anchor="2026-03-22T01:00:00Z")
    )
    assert req.entity == "esx01"
    assert req.sources == ["alert", "event"]
    assert req.anchor_time is not None
    assert IncidentTimelineViewRequest.model_validate(_body(entity="   ")).entity is None


def test_request_rejects_span_over_90_days() -> None:
    with pytest.raises(ValidationError):
        IncidentTimelineViewRequest.model_validate(
            {"from": "2026-01-01T00:00:00Z", "to": "2026-04-02T00:00:00Z"}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"from": "2026-03-22T02:00:00Z", "to": "2026-03-22T02:00:00Z"},
        {"from": "2026-03-22T03:00:00Z"},
        {"sources": []},
        {"sources": ["nope"]},
        {"item_limit": 0},
        {"item_limit": 1001},
        {"min_score": 101},
        {"entity": "x" * 257},
        {"metric_threshold_cpu_pct": 101},
        {"unknown_field": 1},
    ],
)
async def test_invalid_request_is_422(client: AsyncClient, overrides: dict) -> None:
    r = await client.post(URL, json=_body(**overrides))
    assert r.status_code == 422


# --- イベント ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_individual_events_are_listed_with_details(client: AsyncClient) -> None:
    vid = await _vcenter("vc-detail")
    (event_id,) = await _events(
        vid, (10, "VmPoweredOffEvent", "vm-a", 55, {"message": "vm-a was powered off"})
    )
    data = await _post(client)
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["id"] == f"event:{event_id}"
    assert item["kind"] == "event"
    assert item["entity_name"] == "vm-a"
    assert item["entity_type"] == "HostSystem"
    assert item["detail"] == "vm-a was powered off"
    assert item["score"] == 55
    assert item["level"] == "warning"
    assert item["ref"]["event_id"] == event_id
    assert item["ref"]["event_type"] == "VmPoweredOffEvent"
    assert item["vcenter_id"] == str(vid)
    assert item["vcenter_name"] == "vc-detail"
    assert _dt(item["timestamp_utc"]) == _at(10)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("score", "severity", "expected"),
    [
        (85, None, "critical"),
        (80, None, "critical"),
        (65, None, "error"),
        (45, None, "warning"),
        (10, None, "info"),
        (10, "error", "error"),
        (10, "warning", "warning"),
        (85, "warning", "critical"),
        (45, "error", "error"),
    ],
)
async def test_event_level_from_score_and_severity(
    client: AsyncClient, score: int, severity: str | None, expected: str
) -> None:
    vid = await _vcenter()
    await _events(vid, (5, "SomeEvent", "h1", score, {"severity": severity}))
    data = await _post(client)
    assert [i["level"] for i in data["items"]] == [expected]


@pytest.mark.asyncio
async def test_events_below_min_score_are_hidden_but_counted_in_overview(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _events(vid, (5, "LowEvent", "h1", 5), (6, "HighEvent", "h2", 50))
    data = await _post(client, min_score=20)
    assert [i["ref"]["event_type"] for i in data["items"]] == ["HighEvent"]
    assert sum(b["event_total"] for b in data["overview"]) == 2
    assert sum(b["event_notable"] for b in data["overview"]) == 1


@pytest.mark.asyncio
async def test_consecutive_same_events_are_merged(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _events(
        vid,
        (1, "A", "h1", 30),
        (2, "A", "h1", 30),
        (3, "A", "h1", 30),
        (4, "B", "h1", 30),
        (5, "A", "h1", 30),
    )
    data = await _post(client)
    items = data["items"]
    assert [(i["ref"]["event_type"], i["count"]) for i in items] == [("A", 3), ("B", 1), ("A", 1)]
    merged = items[0]
    assert _dt(merged["timestamp_utc"]) == _at(1)
    assert _dt(merged["end_utc"]) == _at(3)


@pytest.mark.asyncio
async def test_same_event_type_on_different_entities_is_not_merged(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _events(vid, (1, "A", "h1", 30), (2, "A", "h2", 30))
    data = await _post(client)
    assert [i["count"] for i in data["items"]] == [1, 1]


@pytest.mark.asyncio
async def test_alert_between_events_prevents_merging(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _events(vid, (1, "A", "h1", 30), (3, "A", "h1", 30))
    async with session_scope() as session:
        rule = AlertRule(name="r-between", rule_type="event_score", alert_level="warning", config={})
        session.add(rule)
        await session.flush()
        session.add(
            AlertHistory(
                rule_id=rule.id,
                alert_level="warning",
                state="firing",
                context_key="Other",
                notified_at=_at(2),
                channel="none",
            )
        )
    data = await _post(client)
    assert [i["kind"] for i in data["items"]] == ["event", "alert", "event"]


@pytest.mark.asyncio
async def test_items_are_sorted_by_timestamp_ascending(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _events(vid, (30, "C", "h3", 30), (10, "A", "h1", 30), (20, "B", "h2", 30))
    data = await _post(client)
    stamps = [_dt(i["timestamp_utc"]) for i in data["items"]]
    assert stamps == sorted(stamps)
    assert len(stamps) == 3


# --- アラート ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alert_history_becomes_alert_item_with_resolved_metric_entity(client: AsyncClient) -> None:
    vid = await _vcenter("vc-alert")
    async with session_scope() as session:
        session.add(
            MetricSample(
                vcenter_id=vid,
                sampled_at=_at(5),
                entity_type="HostSystem",
                entity_moid="host-1",
                entity_name="esx01",
                metric_key="host.cpu.usage_pct",
                value=95.0,
            )
        )
        rule = AlertRule(name="cpu-high", rule_type="metric_threshold", alert_level="critical", config={})
        session.add(rule)
        await session.flush()
        hist = AlertHistory(
            rule_id=rule.id,
            alert_level="critical",
            state="firing",
            context_key=metric_context_key(vid, "host-1"),
            notified_at=_at(6),
            channel="none",
        )
        session.add(hist)
        await session.flush()
        hist_id, rule_id = hist.id, rule.id
    data = await _post(client)
    (item,) = data["items"]
    assert item["id"] == f"alert:{hist_id}"
    assert item["kind"] == "alert"
    assert item["level"] == "critical"
    assert item["entity_name"] == "esx01"
    assert item["vcenter_id"] == str(vid)
    assert item["vcenter_name"] == "vc-alert"
    ref = item["ref"]
    assert ref["alert_history_id"] == hist_id
    assert ref["alert_rule_id"] == rule_id
    assert ref["alert_rule_name"] == "cpu-high"
    assert ref["alert_state"] == "firing"
    assert ref["entity_moid"] == "host-1"
    assert _dt(item["timestamp_utc"]) == _at(6)
    assert sum(b["alert"] for b in data["overview"]) == 1


@pytest.mark.asyncio
async def test_event_score_alert_context_key_is_event_type(client: AsyncClient) -> None:
    await _vcenter()
    async with session_scope() as session:
        rule = AlertRule(name="score-rule", rule_type="event_score", alert_level="warning", config={})
        session.add(rule)
        await session.flush()
        session.add(
            AlertHistory(
                rule_id=rule.id,
                alert_level="error",
                state="firing",
                context_key="VmPoweredOffEvent",
                notified_at=_at(7),
                channel="none",
            )
        )
    data = await _post(client)
    (item,) = data["items"]
    assert item["kind"] == "alert"
    # 発火の通知はルールの現在値ではなく履歴の alert_level を使う（回復は info。別のテストで確認）
    assert item["level"] == "error"
    assert item["ref"]["event_type"] == "VmPoweredOffEvent"
    assert item["ref"]["alert_state"] == "firing"


# --- 俯瞰 --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overview_fills_range_without_gaps(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _events(vid, (1, "A", "h1", 30), (100, "B", "h1", 30))
    data = await _post(client)
    # 2 時間は 1 分幅で 120 本。件数 0 のバケットも含めて隙間なく並ぶ
    assert data["bucket_seconds"] == 60
    starts = [_dt(b["bucket_start_utc"]) for b in data["overview"]]
    assert starts == [T0 + timedelta(minutes=i) for i in range(120)]
    totals = [b["event_total"] for b in data["overview"]]
    assert totals == [1 if i in (1, 100) else 0 for i in range(120)]
    assert _dt(data["from_utc"]) == T0
    assert _dt(data["to_utc"]) == _at(120)


# --- 絞り込み ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entity_filter_is_case_insensitive_substring(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _events(vid, (1, "A", "esx-Alpha-01", 30), (2, "B", "vm-beta", 30))
    data = await _post(client, entity="ALPHA")
    assert [i["entity_name"] for i in data["items"]] == ["esx-Alpha-01"]


@pytest.mark.asyncio
async def test_vcenter_filter(client: AsyncClient) -> None:
    v1 = await _vcenter("vc-one")
    v2 = await _vcenter("vc-two")
    await _events(v1, (1, "A", "h1", 30))
    await _events(v2, (2, "B", "h2", 30))
    data = await _post(client, vcenter_id=str(v2))
    assert [i["vcenter_id"] for i in data["items"]] == [str(v2)]


@pytest.mark.asyncio
async def test_sources_alert_only_excludes_events(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _events(vid, (1, "A", "h1", 30))
    async with session_scope() as session:
        rule = AlertRule(name="r-src", rule_type="event_score", alert_level="warning", config={})
        session.add(rule)
        await session.flush()
        session.add(
            AlertHistory(
                rule_id=rule.id, alert_level="warning", state="firing",
                context_key="A", notified_at=_at(2), channel="none",
            )
        )
    data = await _post(client, sources=["alert"])
    assert [i["kind"] for i in data["items"]] == ["alert"]


# --- 打ち切り ----------------------------------------------------------------------------


async def _five_distinct_events() -> None:
    vid = await _vcenter()
    await _events(
        vid,
        (1, "T1", "h1", 10),
        (2, "T2", "h2", 20),
        (3, "T3", "h3", 90),
        (4, "T4", "h4", 30),
        (5, "T5", "h5", 40),
    )


@pytest.mark.asyncio
async def test_truncation_keeps_highest_level_and_score_without_anchor(client: AsyncClient) -> None:
    await _five_distinct_events()
    data = await _post(client, item_limit=2)
    assert data["truncated"] is True
    assert data["total_items"] == 5
    assert [i["ref"]["event_type"] for i in data["items"]] == ["T3", "T5"]  # 時刻順


@pytest.mark.asyncio
async def test_truncation_keeps_items_nearest_to_anchor(client: AsyncClient) -> None:
    await _five_distinct_events()
    data = await _post(client, item_limit=2, anchor="2026-03-22T00:01:00Z")
    assert data["truncated"] is True
    assert data["total_items"] == 5
    assert [i["ref"]["event_type"] for i in data["items"]] == ["T1", "T2"]
    assert _dt(data["anchor_utc"]) == _at(1)


@pytest.mark.asyncio
async def test_not_truncated_when_within_limit(client: AsyncClient) -> None:
    await _five_distinct_events()
    data = await _post(client, item_limit=5)
    assert data["truncated"] is False
    assert data["total_items"] == 5
    assert len(data["items"]) == 5


# --- ハイライト --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_signal_is_earliest_item_at_warning_or_above(client: AsyncClient) -> None:
    vid = await _vcenter()
    (_, warn_id, _) = await _events(
        vid, (1, "Info", "h1", 10), (5, "Warn", "h2", 45), (8, "Crit", "h3", 90)
    )
    data = await _post(client)
    assert data["highlights"]["first_signal"]["id"] == f"event:{warn_id}"


@pytest.mark.asyncio
async def test_top_entities_are_top_five_by_item_count(client: AsyncClient) -> None:
    vid = await _vcenter()
    specs = []
    minute = 1
    for rank, count in enumerate([6, 5, 4, 3, 2, 1]):
        for j in range(count):
            # 同じ対象でも種別を交互にして、連続によるまとめを避ける
            specs.append((minute, f"T{j % 2}", f"entity-{rank}", 30))
            minute += 1
    await _events(vid, *specs)
    top = (await _post(client, item_limit=1000))["highlights"]["top_entities"]
    assert [t["entity_name"] for t in top] == [f"entity-{i}" for i in range(5)]
    assert [t["item_count"] for t in top] == [6, 5, 4, 3, 2]
    assert _dt(top[0]["first_seen_utc"]) == _at(1)
    assert top[0]["entity_type"] == "HostSystem"


@pytest.mark.asyncio
async def test_new_event_types_exclude_types_seen_in_previous_period(client: AsyncClient) -> None:
    vid = await _vcenter()
    # 期間は 00:00-02:00。直前の同じ長さの期間は前日 22:00-24:00。
    await _events(
        vid,
        (-60, "OldType", "h1", 30),
        (30, "OldType", "h1", 30),
        (40, "NewType", "h2", 70),
        (50, "NewType", "h3", 55),
    )
    new = (await _post(client))["highlights"]["new_event_types"]
    assert [n["event_type"] for n in new] == ["NewType"]
    assert new[0]["count"] == 2
    assert new[0]["max_score"] == 70
    assert _dt(new[0]["first_seen_utc"]) == _at(40)


@pytest.mark.asyncio
async def test_empty_period_returns_200_with_empty_items(client: AsyncClient) -> None:
    data = await _post(client)
    assert data["items"] == []
    assert data["truncated"] is False
    assert data["total_items"] == 0
    assert data["highlights"]["first_signal"] is None
    assert data["highlights"]["top_entities"] == []
    assert data["highlights"]["new_event_types"] == []
    assert len(data["overview"]) >= 1


# --- 同時実行数の上限 --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_503_when_concurrency_limit_is_reached(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(require_settings(), "context_aggregation_concurrency", 1)
    with aggregation_slot("someone-else", global_limit=1, per_owner_limit=1):
        r = await client.post(URL, json=_body())
    assert r.status_code == 503
    assert r.headers.get("retry-after")
    # 枠が空けば通る
    assert (await client.post(URL, json=_body())).status_code == 200


# --- 期間・上限（サービス側の検証） -------------------------------------------------------


@pytest.mark.asyncio
async def test_from_and_to_in_the_same_second_is_400(client: AsyncClient) -> None:
    r = await client.post(
        URL, json=_body(**{"from": "2026-03-22T00:00:00.100Z", "to": "2026-03-22T00:00:00.900Z"})
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_too_many_event_rows_is_422(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    vid = await _vcenter()
    await _events(vid, (1, "A", "h1", 30), (2, "B", "h2", 30), (3, "C", "h3", 30), (4, "Low", "h4", 0))
    monkeypatch.setattr(require_settings(), "context_aggregation_max_rows", 2)
    r = await client.post(URL, json=_body())
    assert r.status_code == 422
    assert "vCenter を指定" in r.json()["detail"]

    # min_score 未満の行は読まないので、上限ちょうどなら通る（黙って切らない）
    monkeypatch.setattr(require_settings(), "context_aggregation_max_rows", 3)
    data = await _post(client)
    assert data["total_items"] == 3


@pytest.mark.asyncio
async def test_too_many_alert_rows_is_422(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async with session_scope() as session:
        rule = AlertRule(name="r-many", rule_type="event_score", alert_level="warning", config={})
        session.add(rule)
        await session.flush()
        for minute in (1, 2):
            session.add(
                AlertHistory(
                    rule_id=rule.id, alert_level="warning", state="firing",
                    context_key="X", notified_at=_at(minute), channel="none",
                )
            )
    monkeypatch.setattr(require_settings(), "context_aggregation_max_rows", 1)
    assert (await client.post(URL, json=_body())).status_code == 422
    assert (await client.post(URL, json=_body(sources=["event"]))).status_code == 200


# --- 俯瞰と一覧の整合 ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overview_notable_matches_listed_events_before_merging(client: AsyncClient) -> None:
    v1 = await _vcenter("vc-a")
    v2 = await _vcenter("vc-b")
    await _events(
        v1,
        (1, "A", "esx-01", 30),
        (2, "A", "esx-01", 30),
        (3, "A", "esx-01", 5),
        (4, "B", "vm-01", 50),
    )
    await _events(v2, (5, "A", "esx-01", 30))
    data = await _post(client, min_score=10, vcenter_id=str(v1), entity="ESX")
    listed = sum(i["count"] for i in data["items"] if i["kind"] == "event")
    assert listed == 2
    assert sum(b["event_notable"] for b in data["overview"]) == listed
    assert sum(b["event_total"] for b in data["overview"]) == 3


@pytest.mark.asyncio
async def test_metric_and_log_sources_return_nothing_yet(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _events(vid, (1, "A", "h1", 30))
    data = await _post(client, sources=["metric", "log"])
    assert data["items"] == [] and data["total_items"] == 0
    for b in data["overview"]:
        assert (b["event_total"], b["event_notable"], b["alert"], b["metric_breach"], b["log_error"]) == (0, 0, 0, 0, 0)
    assert data["highlights"]["new_event_types"] == []


@pytest.mark.asyncio
async def test_entity_filter_treats_like_wildcards_literally(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _events(vid, (1, "A", "esx_01", 30), (2, "B", "esxA01", 30), (3, "C", "100%-vm", 30))
    assert [i["entity_name"] for i in (await _post(client, entity="x_0"))["items"]] == ["esx_01"]
    assert [i["entity_name"] for i in (await _post(client, entity="0%"))["items"]] == ["100%-vm"]


# --- アラートの対象と絞り込み -------------------------------------------------------------


async def _alert_history(rule_type: str, context_key: str, minute: float, *, name: str) -> int:
    async with session_scope() as session:
        rule = AlertRule(name=name, rule_type=rule_type, alert_level="warning", config={})
        session.add(rule)
        await session.flush()
        hist = AlertHistory(
            rule_id=rule.id, alert_level="warning", state="firing",
            context_key=context_key, notified_at=_at(minute), channel="none",
        )
        session.add(hist)
        await session.flush()
        return hist.id


async def _metric_sample(vid: uuid.UUID, moid: str, name: str, minute: float) -> None:
    async with session_scope() as session:
        session.add(
            MetricSample(
                vcenter_id=vid, sampled_at=_at(minute), entity_type="HostSystem",
                entity_moid=moid, entity_name=name, metric_key="host.cpu.usage_pct", value=90.0,
            )
        )


@pytest.mark.asyncio
async def test_metric_alert_uses_latest_sample_and_same_moid_on_other_vcenter_is_not_mixed(
    client: AsyncClient,
) -> None:
    v1 = await _vcenter("vc-m1")
    v2 = await _vcenter("vc-m2")
    await _metric_sample(v1, "host-1", "old-name", 1)
    await _metric_sample(v1, "host-1", "esx-new", 2)
    await _metric_sample(v2, "host-1", "other-vc-host", 3)
    await _alert_history("metric_threshold", metric_context_key(v1, "host-1"), 4, name="m-latest")
    (item,) = (await _post(client))["items"]
    assert item["entity_name"] == "esx-new"
    assert item["entity_type"] == "HostSystem"
    assert item["vcenter_name"] == "vc-m1"


@pytest.mark.asyncio
async def test_unresolved_metric_alert_keeps_only_moid(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _alert_history("metric_threshold", metric_context_key(vid, "host-9"), 4, name="m-unresolved")
    (item,) = (await _post(client))["items"]
    assert item["entity_name"] is None
    assert item["entity_type"] is None
    assert item["ref"]["entity_moid"] == "host-9"
    assert item["vcenter_id"] == str(vid)


@pytest.mark.asyncio
async def test_vcenter_filter_keeps_event_score_alerts_and_drops_other_vcenter_metric_alerts(
    client: AsyncClient,
) -> None:
    v1 = await _vcenter("vc-f1")
    v2 = await _vcenter("vc-f2")
    await _metric_sample(v1, "host-1", "esx-1", 1)
    await _metric_sample(v2, "host-2", "esx-2", 1)
    keep_metric = await _alert_history("metric_threshold", metric_context_key(v1, "host-1"), 2, name="m-v1")
    await _alert_history("metric_threshold", metric_context_key(v2, "host-2"), 3, name="m-v2")
    keep_score = await _alert_history("event_score", "SomeEvent", 4, name="s-any")
    data = await _post(client, vcenter_id=str(v1))
    assert [i["id"] for i in data["items"]] == [f"alert:{keep_metric}", f"alert:{keep_score}"]
    assert sum(b["alert"] for b in data["overview"]) == 2


@pytest.mark.asyncio
async def test_entity_filter_keeps_only_alerts_with_matching_entity(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _metric_sample(vid, "host-1", "esx-Alpha", 1)
    await _metric_sample(vid, "host-2", "esx-beta", 1)
    keep = await _alert_history("metric_threshold", metric_context_key(vid, "host-1"), 2, name="m-alpha")
    await _alert_history("metric_threshold", metric_context_key(vid, "host-2"), 3, name="m-beta")
    await _alert_history("event_score", "SomeEvent", 4, name="s-none")
    data = await _post(client, entity="alpha")
    assert [i["id"] for i in data["items"]] == [f"alert:{keep}"]
    assert sum(b["alert"] for b in data["overview"]) == 1


@pytest.mark.asyncio
async def test_alert_title_names_rule_and_state(client: AsyncClient) -> None:
    await _alert_history("event_score", "SomeEvent", 4, name="CPU 高負荷")
    (item,) = (await _post(client))["items"]
    assert item["title"] == "CPU 高負荷 が発火"


@pytest.mark.asyncio
async def test_alert_and_event_at_same_time_list_alert_first(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _events(vid, (2, "A", "h1", 30))
    await _alert_history("event_score", "A", 2, name="r-same-time")
    data = await _post(client)
    assert [i["kind"] for i in data["items"]] == ["alert", "event"]


# --- ハイライトと絞り込み -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_event_types_apply_vcenter_filter_to_previous_period(client: AsyncClient) -> None:
    v1 = await _vcenter("vc-p1")
    v2 = await _vcenter("vc-p2")
    await _events(v2, (-60, "SeenElsewhere", "h9", 30))
    await _events(v1, (-30, "SeenLowScore", "h1", 0))
    await _events(v1, (10, "SeenElsewhere", "h1", 30), (20, "SeenLowScore", "h1", 30))
    new = (await _post(client, vcenter_id=str(v1)))["highlights"]["new_event_types"]
    # 別の vCenter で出ていた種別は新しい扱い、スコア 0 でも直前に出ていた種別は除く
    assert [n["event_type"] for n in new] == ["SeenElsewhere"]


@pytest.mark.asyncio
async def test_first_signal_carries_vcenter_name_even_when_truncated_away(client: AsyncClient) -> None:
    vid = await _vcenter("vc-signal")
    (warn_id, *_rest) = await _events(vid, (1, "Warn", "h1", 45), (50, "Crit", "h2", 90))
    data = await _post(client, item_limit=1)
    assert [i["ref"]["event_type"] for i in data["items"]] == ["Crit"]
    signal = data["highlights"]["first_signal"]
    assert signal["id"] == f"event:{warn_id}"
    assert signal["vcenter_name"] == "vc-signal"


@pytest.mark.asyncio
async def test_alert_uses_occurred_at_not_the_redelivery_time(client: AsyncClient) -> None:
    """再送で notified_at が期間の外へずれても、発生時刻（occurred_at）で期間に入り、その時刻に並ぶ。"""
    async with session_scope() as session:
        rule = AlertRule(name="r-retry", rule_type="event_score", alert_level="warning", config={})
        session.add(rule)
        await session.flush()
        inside = AlertHistory(
            rule_id=rule.id, alert_level="warning", state="firing", context_key="X",
            occurred_at=_at(10), notified_at=_at(200), channel="email",
        )
        outside = AlertHistory(
            rule_id=rule.id, alert_level="warning", state="firing", context_key="Y",
            occurred_at=_at(-5), notified_at=_at(30), channel="email",
        )
        session.add_all([inside, outside])
        await session.flush()
        inside_id = inside.id
    data = await _post(client)
    assert [i["id"] for i in data["items"]] == [f"alert:{inside_id}"]
    assert _dt(data["items"][0]["timestamp_utc"]) == _at(10)


@pytest.mark.asyncio
async def test_resolved_alert_is_info_and_overview_counts_only_firing(client: AsyncClient) -> None:
    async with session_scope() as session:
        rule = AlertRule(name="CPU 高負荷", rule_type="event_score", alert_level="critical", config={})
        session.add(rule)
        await session.flush()
        for minute, state in ((1, "firing"), (2, "resolved"), (3, "stale")):
            session.add(
                AlertHistory(
                    rule_id=rule.id, alert_level="critical", state=state, context_key="X",
                    notified_at=_at(minute), channel="none",
                )
            )
    data = await _post(client)
    assert [(i["title"], i["level"]) for i in data["items"]] == [
        ("CPU 高負荷 が発火", "critical"),
        ("CPU 高負荷 が回復", "info"),
        ("CPU 高負荷 のデータが古い", "warning"),
    ]
    assert sum(b["alert"] for b in data["overview"]) == 1
    assert data["highlights"]["first_signal"]["title"] == "CPU 高負荷 が発火"


@pytest.mark.asyncio
async def test_top_entities_carry_vcenter(client: AsyncClient) -> None:
    v1 = await _vcenter("vc-top-1")
    v2 = await _vcenter("vc-top-2")
    await _events(v1, (1, "A", "esx01", 30))
    await _events(v2, (2, "B", "esx01", 30), (3, "C", "esx01", 30))
    top = (await _post(client))["highlights"]["top_entities"]
    assert [(t["entity_name"], t["vcenter_id"], t["vcenter_name"], t["item_count"]) for t in top] == [
        ("esx01", str(v2), "vc-top-2", 2),
        ("esx01", str(v1), "vc-top-1", 1),
    ]


# --- レビュー指摘: アラートの SQL・対象解決・message の読み方 ---------------------------


async def _metric_alert(vid: uuid.UUID, moid: str, minute: float, *, name: str, config: dict | None = None) -> int:
    async with session_scope() as session:
        rule = AlertRule(name=name, rule_type="metric_threshold", alert_level="warning", config=config or {})
        session.add(rule)
        await session.flush()
        hist = AlertHistory(
            rule_id=rule.id, alert_level="warning", state="firing",
            context_key=metric_context_key(vid, moid), notified_at=_at(minute), channel="none",
        )
        session.add(hist)
        await session.flush()
        return hist.id


@pytest.mark.asyncio
async def test_vcenter_filter_is_applied_in_sql_before_the_alert_row_limit(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    v1 = await _vcenter("vc-e1")
    v2 = await _vcenter("vc-e2")
    keep = await _metric_alert(v1, "host-1", 1, name="m-e1")
    await _metric_alert(v2, "host-2", 2, name="m-e2a")
    await _metric_alert(v2, "host-3", 3, name="m-e2b")
    monkeypatch.setattr(require_settings(), "context_aggregation_max_rows", 1)
    data = await _post(client, vcenter_id=str(v1))
    assert [i["id"] for i in data["items"]] == [f"alert:{keep}"]

    r = await client.post(URL, json=_body())
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "期間を短く" in detail and "vCenter" not in detail


@pytest.mark.asyncio
async def test_legacy_metric_context_key_is_excluded_when_filtering_by_vcenter(client: AsyncClient) -> None:
    vid = await _vcenter("vc-legacy")
    legacy = await _alert_history("metric_threshold", "host-1", 1, name="m-legacy")
    assert (await _post(client, vcenter_id=str(vid)))["items"] == []
    (item,) = (await _post(client))["items"]
    assert item["id"] == f"alert:{legacy}"
    assert item["entity_name"] is None and item["vcenter_id"] is None
    assert item["ref"]["entity_moid"] == "host-1"


@pytest.mark.asyncio
async def test_metric_entity_name_is_the_one_at_the_alert_time(client: AsyncClient) -> None:
    """名前はアラートの occurred_at の時点のもの。期間内でも後の改名は拾わない（期間の終わりには寄せない）。"""
    vid = await _vcenter("vc-g")
    await _metric_sample(vid, "host-1", "at-incident", 30)
    await _metric_sample(vid, "host-1", "renamed-in-period", 100)
    await _metric_sample(vid, "host-1", "renamed-after-period", 130)  # 期間の終わり（120 分）より後
    await _metric_alert(vid, "host-1", 50, name="m-g")
    (item,) = (await _post(client))["items"]
    assert item["entity_name"] == "at-incident"


@pytest.mark.asyncio
async def test_metric_entity_is_not_resolved_from_samples_far_before_the_alert(client: AsyncClient) -> None:
    """さかのぼる幅（既定 6 時間）はアラートの時刻から測る。期間の開始から測ると -360 分まで届いてしまう。"""
    vid = await _vcenter("vc-g2")
    await _metric_sample(vid, "host-1", "too-old", 50 - 6 * 60 - 1)
    await _metric_alert(vid, "host-1", 50, name="m-g2")
    (item,) = (await _post(client))["items"]
    assert item["entity_name"] is None
    assert item["ref"]["entity_moid"] == "host-1"


@pytest.mark.asyncio
async def test_metric_entity_resolution_without_metric_key_filter(client: AsyncClient) -> None:
    """ルールのどれかに metric_key が無いときは指標で絞らない（metric_keys が None の経路）。"""
    vid = await _vcenter("vc-none")
    async with session_scope() as session:
        session.add_all(
            [
                MetricSample(
                    vcenter_id=vid, sampled_at=_at(5), entity_type="HostSystem", entity_moid="host-1",
                    entity_name="esx-mem-only", metric_key="host.mem.usage_pct", value=90.0,
                ),
                MetricSample(
                    vcenter_id=vid, sampled_at=_at(5), entity_type="HostSystem", entity_moid="host-2",
                    entity_name="esx-cpu", metric_key="host.cpu.usage_pct", value=90.0,
                ),
            ]
        )
    await _metric_alert(vid, "host-1", 10, name="m-nokey")
    await _metric_alert(vid, "host-2", 11, name="m-cpu", config={"metric_key": "host.cpu.usage_pct"})
    data = await _post(client)
    assert [i["entity_name"] for i in data["items"]] == ["esx-mem-only", "esx-cpu"]
    assert [i["ref"]["metric_key"] for i in data["items"]] == [None, "host.cpu.usage_pct"]


@pytest.mark.asyncio
async def test_alert_on_deleted_vcenter_is_listed_without_names(client: AsyncClient) -> None:
    vid = await _vcenter("vc-deleted")
    await _metric_sample(vid, "host-1", "esx-gone", 1)
    hist_id = await _metric_alert(vid, "host-1", 2, name="m-deleted")
    async with session_scope() as session:
        await session.delete(await session.get(VCenter, vid))
    (item,) = (await _post(client))["items"]
    assert item["id"] == f"alert:{hist_id}"
    assert item["vcenter_id"] == str(vid)
    assert item["vcenter_name"] is None
    assert item["entity_name"] is None
    assert item["ref"]["entity_moid"] == "host-1"


@pytest.mark.asyncio
async def test_event_list_query_does_not_read_messages(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """一覧の SELECT は message を読まず、残った項目と first_signal の分だけ後から引く。"""
    from sqlalchemy.ext.asyncio import AsyncSession

    vid = await _vcenter("vc-msg")
    (warn_id, _a1, _a2, _crit) = await _events(
        vid,
        (1, "Warn", "h1", 45, {"message": "first warning"}),
        (60, "A", "h2", 30, {"message": "a-first"}),
        (61, "A", "h2", 30, {"message": "a-second"}),
        (90, "Crit", "h3", 90, {"message": "critical!"}),
    )
    captured: list[str] = []
    original = AsyncSession.execute

    async def spy(self, statement, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(str(statement))
        return await original(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", spy)
    data = await _post(client, item_limit=2, anchor="2026-03-22T01:00:30Z")
    monkeypatch.setattr(AsyncSession, "execute", original)

    assert [(i["ref"]["event_type"], i["count"], i["detail"]) for i in data["items"]] == [
        ("A", 2, "a-first"),
        ("Crit", 1, "critical!"),
    ]
    signal = data["highlights"]["first_signal"]
    assert signal["id"] == f"event:{warn_id}" and signal["detail"] == "first warning"
    list_sql = [s for s in captured if "ORDER BY events.occurred_at, events.id" in s]
    assert list_sql and all("events.message" not in s for s in list_sql)


@pytest.mark.asyncio
async def test_more_than_500_ids_and_types_are_split_into_chunks(client: AsyncClient) -> None:
    """IN の分割（500 件ごと）: 直前の期間の種別と、message の後引きの両方。"""
    vid = await _vcenter("vc-chunk")
    specs = [(i * 0.1, f"T{i:03d}", f"h{i}", 30, {"message": f"m{i}"}) for i in range(501)]
    specs.append((-30, "T500", "h500", 0))  # 直前の期間に出ていた種別（501 番目の候補）
    await _events(vid, *specs)
    data = await _post(client, item_limit=1000)
    assert data["total_items"] == 501
    assert all(i["detail"] == f"m{int(i['ref']['event_type'][1:])}" for i in data["items"])
    new = data["highlights"]["new_event_types"]
    assert len(new) == 10 and "T500" not in {n["event_type"] for n in new}
