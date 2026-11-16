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


def _message_fetch_ids(statements: list, table: str) -> set[int]:
    """横取りした問い合わせのうち ``{table}.message`` を読むものについて、IN に渡した id をすべて集める。"""
    ids: set[int] = set()
    for stmt in statements:
        if f"{table}.message" not in str(stmt):
            continue
        for value in stmt.compile().params.values():
            if isinstance(value, (list, tuple)):
                ids.update(int(v) for v in value)
    return ids


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
                # 対象名の解決にだけ使う。閾値（80%）未満にして、超過区間の行を出さない
                value=10.0,
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
    """アラートの対象名の解決に使うサンプル。閾値未満にして、超過区間の行を出さない。"""
    async with session_scope() as session:
        session.add(
            MetricSample(
                vcenter_id=vid, sampled_at=_at(minute), entity_type="HostSystem",
                entity_moid=moid, entity_name=name, metric_key="host.cpu.usage_pct", value=10.0,
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
                    entity_name="esx-mem-only", metric_key="host.mem.usage_pct", value=10.0,
                ),
                MetricSample(
                    vcenter_id=vid, sampled_at=_at(5), entity_type="HostSystem", entity_moid="host-2",
                    entity_name="esx-cpu", metric_key="host.cpu.usage_pct", value=10.0,
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
    (warn_id, a1, _a2, crit) = await _events(
        vid,
        (1, "Warn", "h1", 45, {"message": "first warning"}),
        (60, "A", "h2", 30, {"message": "a-first"}),
        (61, "A", "h2", 30, {"message": "a-second"}),
        (90, "Crit", "h3", 90, {"message": "critical!"}),
    )
    captured: list = []
    original = AsyncSession.execute

    async def spy(self, statement, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(statement)
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
    sql = [str(s) for s in captured]
    list_sql = [s for s in sql if "ORDER BY events.occurred_at, events.id" in s]
    assert list_sql and all("events.message" not in s for s in list_sql)
    # message を引くのは、残った行（まとめた行は最初のイベント）と first_signal の id だけ
    assert _message_fetch_ids(captured, "events") == {a1, crit, warn_id}


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


# --- メトリクスの超過区間 ------------------------------------------------------------------
#
# 閾値の既定は CPU 80% / メモリ 85%。収集間隔の既定は 5 分で、隣のサンプルとの間隔が
# effective_metric_staleness_window_seconds（既定は収集間隔 × 3 = 15 分）以内なら同じ区間につなぐ。

CPU = "host.cpu.usage_pct"
MEM = "host.mem.usage_pct"


async def _series(
    vid: uuid.UUID,
    moid: str,
    points: list[tuple[float, float]],
    *,
    key: str = CPU,
    name: str = "esx01",
    entity_type: str = "HostSystem",
) -> list[int]:
    """points は (分, 値) の列。挿入した MetricSample の id を返す。"""
    async with session_scope() as session:
        rows = [
            MetricSample(
                vcenter_id=vid, sampled_at=_at(minute), entity_type=entity_type,
                entity_moid=moid, entity_name=name, metric_key=key, value=value,
            )
            for minute, value in points
        ]
        session.add_all(rows)
        await session.flush()
        return [r.id for r in rows]


def _metrics(data: dict) -> list[dict]:
    return [i for i in data["items"] if i["kind"] == "metric"]


def _span(item: dict) -> tuple[datetime, datetime | None]:
    end = item["end_utc"]
    return _dt(item["timestamp_utc"]), (_dt(end) if end else None)


@pytest.mark.asyncio
async def test_metric_consecutive_breach_becomes_one_interval(client: AsyncClient) -> None:
    vid = await _vcenter("vc-metric")
    ids = await _series(vid, "host-1", [(0, 50), (5, 85), (10, 92.5), (15, 88), (20, 60)])
    data = await _post(client)
    (item,) = _metrics(data)
    assert item["id"] == f"metric:{ids[1]}"
    assert _span(item) == (_at(5), _at(15))
    assert item["title"] == "CPU 使用率が閾値（80%）を超過"
    assert item["detail"] == "ピーク 92.5%、サンプル 3 件"
    assert item["level"] == "warning"
    assert item["entity_name"] == "esx01"
    assert item["entity_type"] == "HostSystem"
    assert item["vcenter_id"] == str(vid)
    assert item["vcenter_name"] == "vc-metric"
    assert item["count"] == 1
    assert item["score"] is None
    assert item["ref"]["metric_key"] == CPU
    assert item["ref"]["entity_moid"] == "host-1"
    assert item["ref"]["event_id"] is None and item["ref"]["log_id"] is None
    # 構造化した値（画面がタイムゾーンの設定で時刻を表示するため）
    assert item["ref"]["threshold_pct"] == 80
    assert item["ref"]["peak_value"] == 92.5
    assert _dt(item["ref"]["peak_at_utc"]) == _at(10)
    assert item["ref"]["sample_count"] == 3
    assert item["ref"]["continues_from_before"] is False


@pytest.mark.asyncio
async def test_metric_interval_is_split_by_a_sample_below_threshold(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _series(vid, "host-1", [(0, 85), (5, 79.9), (10, 85)])
    items = _metrics(await _post(client))
    assert [_span(i) for i in items] == [(_at(0), None), (_at(10), None)]
    assert all(i["detail"] == "ピーク 85%、サンプル 1 件" for i in items)
    assert [_dt(i["ref"]["peak_at_utc"]) for i in items] == [_at(0), _at(10)]


@pytest.mark.asyncio
async def test_metric_interval_survives_missing_samples_within_the_gap_limit(client: AsyncClient) -> None:
    vid = await _vcenter()
    # 5 → 20 分は 15 分空く（上限ちょうど）のでつなぐ。20 → 36 分は 16 分空くので区切る
    await _series(vid, "host-1", [(0, 85), (5, 86), (20, 87), (36, 88)])
    items = _metrics(await _post(client))
    assert [_span(i) for i in items] == [(_at(0), _at(20)), (_at(36), None)]
    assert "サンプル 3 件" in items[0]["detail"]


@pytest.mark.asyncio
async def test_metric_gap_limit_follows_the_staleness_window_setting(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    vid = await _vcenter()
    await _series(vid, "host-1", [(0, 85), (20, 86)])
    assert len(_metrics(await _post(client))) == 2
    monkeypatch.setattr(require_settings(), "metric_staleness_window_seconds", 20 * 60)
    assert [_span(i) for i in _metrics(await _post(client))] == [(_at(0), _at(20))]


@pytest.mark.asyncio
async def test_metric_threshold_is_inclusive(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _series(vid, "host-1", [(0, 80.0), (5, 79.99)])
    await _series(vid, "host-1", [(0, 85.0), (5, 84.99)], key=MEM)
    items = _metrics(await _post(client))
    assert sorted((i["ref"]["metric_key"], _span(i)) for i in items) == [
        (CPU, (_at(0), None)),
        (MEM, (_at(0), None)),
    ]


@pytest.mark.asyncio
async def test_metric_intervals_are_split_by_metric_host_and_vcenter(client: AsyncClient) -> None:
    v1 = await _vcenter("vc-x1")
    v2 = await _vcenter("vc-x2")
    # 同じ moid が別の vCenter にある。片方の vCenter の超過がもう片方につながらない
    await _series(v1, "host-1", [(0, 90), (10, 90)], name="esx-a")
    await _series(v2, "host-1", [(5, 90)], name="esx-b")
    await _series(v1, "host-1", [(5, 90)], key=MEM, name="esx-a")
    await _series(v1, "host-2", [(5, 90)], name="esx-c")
    items = _metrics(await _post(client))
    got = sorted((i["vcenter_name"], i["ref"]["entity_moid"], i["ref"]["metric_key"], _span(i)) for i in items)
    assert got == [
        ("vc-x1", "host-1", CPU, (_at(0), _at(10))),
        ("vc-x1", "host-1", MEM, (_at(5), None)),
        ("vc-x1", "host-2", CPU, (_at(5), None)),
        ("vc-x2", "host-1", CPU, (_at(5), None)),
    ]
    mem = next(i for i in items if i["ref"]["metric_key"] == MEM)
    assert mem["title"] == "メモリ使用率が閾値（85%）を超過"


@pytest.mark.asyncio
async def test_metric_interval_continuing_from_before_the_period(client: AsyncClient) -> None:
    vid = await _vcenter()
    # host-1: 期間の前から続く。開始・ピーク・件数は期間内のサンプルだけで決める
    ids = await _series(vid, "host-1", [(-10, 99), (-5, 90), (0, 85), (5, 88)])
    # host-2: 期間の前に終わった超過（-5 分で閾値未満）は出さない
    await _series(vid, "host-2", [(-10, 90), (-5, 50), (5, 90)], name="esx02")
    # host-3: 期間の前の超過から 16 分空いている（つながらない）
    await _series(vid, "host-3", [(-11, 90), (5, 90)], name="esx03")
    items = {i["ref"]["entity_moid"]: i for i in _metrics(await _post(client))}
    assert items["host-1"]["id"] == f"metric:{ids[2]}"
    assert _span(items["host-1"]) == (_at(0), _at(5))
    assert items["host-1"]["detail"] == "ピーク 88%、サンプル 2 件、期間の開始前から継続"
    ref = items["host-1"]["ref"]
    assert (ref["peak_value"], _dt(ref["peak_at_utc"]), ref["sample_count"], ref["continues_from_before"]) == (
        88, _at(5), 2, True,
    )
    assert items["host-2"]["ref"]["continues_from_before"] is False
    assert _span(items["host-2"]) == (_at(5), None)
    assert "期間の開始前" not in items["host-2"]["detail"]
    assert "期間の開始前" not in items["host-3"]["detail"]


@pytest.mark.asyncio
async def test_metric_threshold_from_request_changes_result(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _series(vid, "host-1", [(0, 85)])
    assert _metrics(await _post(client, metric_threshold_cpu_pct=90)) == []
    (item,) = _metrics(await _post(client, metric_threshold_cpu_pct=70))
    assert item["title"] == "CPU 使用率が閾値（70%）を超過"
    (item,) = _metrics(await _post(client, metric_threshold_cpu_pct=82.5))
    assert item["title"] == "CPU 使用率が閾値（82.5%）を超過"
    assert item["ref"]["threshold_pct"] == 82.5


@pytest.mark.asyncio
async def test_metric_lists_every_breaching_host_beyond_top_15(client: AsyncClient) -> None:
    vid = await _vcenter()
    for n in range(20):
        await _series(vid, f"host-{n}", [(1, 81 + n * 0.1)], name=f"esx{n:02d}")
    items = _metrics(await _post(client))
    assert sorted(i["entity_name"] for i in items) == [f"esx{n:02d}" for n in range(20)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("threshold", "peak", "expected"),
    [
        (80, 80, "warning"),
        (80, 94.99, "warning"),
        (80, 95, "error"),  # 95% 以上は error
        (60, 74.99, "warning"),
        (60, 75, "error"),  # 閾値 + 15 ポイント以上も error
    ],
)
async def test_metric_level_from_peak_and_threshold(
    client: AsyncClient, threshold: float, peak: float, expected: str
) -> None:
    vid = await _vcenter()
    await _series(vid, "host-1", [(0, threshold), (5, peak)])
    (item,) = _metrics(await _post(client, metric_threshold_cpu_pct=threshold))
    assert item["level"] == expected


@pytest.mark.asyncio
async def test_metric_disk_and_network_counters_are_not_judged_by_percent_thresholds(client: AsyncClient) -> None:
    """ディスク系・ネットワーク系の指標は KB/s なので、% の閾値は当てない。"""
    vid = await _vcenter()
    for key in (
        "host.disk.usage_pct", "host.disk.read_kbps", "host.disk.write_kbps",
        "host.net.bytes_rx_kbps", "host.net.bytes_tx_kbps", "host.net.usage_kbps",
    ):
        await _series(vid, "host-1", [(0, 5000.0)], key=key)
    data = await _post(client, metric_threshold_disk_pct=0, metric_threshold_network_pct=0)
    assert _metrics(data) == []
    assert sum(b["metric_breach"] for b in data["overview"]) == 0


@pytest.mark.asyncio
async def test_metric_overview_counts_every_bucket_an_interval_touches(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _series(vid, "host-1", [(5, 90), (10, 90), (15, 90)])
    await _series(vid, "host-2", [(10.5, 90)], name="esx02")
    data = await _post(client)  # 2 時間は 1 分幅
    breach = [b["metric_breach"] for b in data["overview"]]
    assert breach[4] == 0 and breach[16] == 0
    assert breach[5:16] == [1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1]
    assert sum(b["event_total"] + b["alert"] + b["log_error"] for b in data["overview"]) == 0


@pytest.mark.asyncio
async def test_metric_overview_starts_at_bucket_zero_for_interval_continuing_from_before(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _series(vid, "host-1", [(-5, 90), (0, 90), (2, 90)])
    breach = [b["metric_breach"] for b in (await _post(client))["overview"]]
    assert breach[:4] == [1, 1, 1, 0]


@pytest.mark.asyncio
async def test_metric_entity_filter_uses_sample_name_and_vcenter_filter(client: AsyncClient) -> None:
    v1 = await _vcenter("vc-f1")
    v2 = await _vcenter("vc-f2")
    await _series(v1, "host-1", [(0, 90)], name="esx-Alpha")
    await _series(v1, "host-2", [(0, 90)], name="esx-beta")
    await _series(v2, "host-1", [(0, 90)], name="esx-alpha-other")
    assert sorted(i["entity_name"] for i in _metrics(await _post(client, entity="ALPHA"))) == [
        "esx-Alpha", "esx-alpha-other",
    ]
    data = await _post(client, entity="alpha", vcenter_id=str(v1))
    assert [i["entity_name"] for i in _metrics(data)] == ["esx-Alpha"]
    assert sum(b["metric_breach"] for b in data["overview"]) == 1


@pytest.mark.asyncio
async def test_metric_interval_uses_latest_non_blank_sample_name(client: AsyncClient) -> None:
    vid = await _vcenter()
    async with session_scope() as session:
        for minute, name in ((0, "old-name"), (5, "new-name"), (10, "  ")):
            session.add(
                MetricSample(
                    vcenter_id=vid, sampled_at=_at(minute), entity_type="HostSystem",
                    entity_moid="host-1", entity_name=name, metric_key=CPU, value=90,
                )
            )
    await _series(vid, "host-9", [(0, 90)], name="")
    items = {i["ref"]["entity_moid"]: i for i in _metrics(await _post(client))}
    assert items["host-1"]["entity_name"] == "new-name"
    assert _span(items["host-1"]) == (_at(0), _at(10))
    # 名前が空のサンプルしか無いときは moid を名前にする
    assert items["host-9"]["entity_name"] == "host-9"


@pytest.mark.asyncio
async def test_metric_interval_is_first_signal_and_sorts_after_event_at_same_time(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _series(vid, "host-1", [(2, 90)])
    await _events(vid, (2, "A", "h1", 30), (5, "Warn", "h2", 45))
    data = await _post(client)
    assert [i["kind"] for i in data["items"]] == ["event", "metric", "event"]
    assert data["highlights"]["first_signal"]["kind"] == "metric"


@pytest.mark.asyncio
async def test_unrequested_sources_issue_no_queries(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    vid = await _vcenter()
    await _series(vid, "host-1", [(0, 90)])
    captured: list[str] = []
    original = AsyncSession.execute

    async def spy(self, statement, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(str(statement))
        return await original(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", spy)
    await _post(client, sources=["event", "alert"])
    assert captured and not any("metric_intervals" in s or "log_records" in s for s in captured)
    captured.clear()
    await _post(client, sources=["metric"])
    assert any("metric_intervals" in s for s in captured)
    assert not any("events" in s or "alert_history" in s or "log_records" in s for s in captured)


# --- エラーログ ------------------------------------------------------------------------------
#
# 対象は重大度が error 以上（大文字小文字と前後の空白は無視）のログ。時刻は effective_at。
# level は error / err が warning、critical / crit / fatal / panic / alert / emerg が error。

_offsets = itertools.count(1)


async def _logs(vid: uuid.UUID, *specs: tuple) -> list[int]:
    """spec は (分, severity, message) か、それに dict（host / log_kind / occurred_at など）を足したもの。"""
    from vcenter_event_assistant.db.models import LogRecord

    async with session_scope() as session:
        rows = []
        for spec in specs:
            minute, severity, message, *rest = spec
            extra = dict(rest[0]) if rest else {}
            row = LogRecord(
                vcenter_id=vid,
                collector_id="test.logs",
                source_id=extra.pop("source_id", "src-1"),
                host=extra.pop("host", "esx01.example.com"),
                log_kind=extra.pop("log_kind", "vmkernel"),
                file_generation="g1",
                byte_offset=next(_offsets),
                occurred_at=extra.pop("occurred_at", None),
                collected_at=_at(minute),
                effective_at=_at(minute),
                severity=severity,
                message=message,
                **extra,
            )
            session.add(row)
            rows.append(row)
        await session.flush()
        return [r.id for r in rows]


def _log_items(data: dict) -> list[dict]:
    return [i for i in data["items"] if i["kind"] == "log"]


@pytest.mark.asyncio
async def test_log_error_becomes_log_item(client: AsyncClient) -> None:
    vid = await _vcenter("vc-log")
    (log_id,) = await _logs(vid, (10, "error", "vmkernel: lost access to volume", {"log_kind": "vmkernel"}))
    data = await _post(client)
    (item,) = _log_items(data)
    assert item["id"] == f"log:{log_id}"
    assert _dt(item["timestamp_utc"]) == _at(10)
    assert item["end_utc"] is None
    assert item["level"] == "warning"
    assert item["title"] == "esx01.example.com vmkernel"
    assert item["detail"] == "vmkernel: lost access to volume"
    assert item["entity_name"] == "esx01.example.com"
    assert item["entity_type"] == "host"
    assert item["vcenter_id"] == str(vid)
    assert item["vcenter_name"] == "vc-log"
    assert item["count"] == 1
    assert item["score"] is None
    assert item["ref"]["log_id"] == log_id
    # メトリクス用の構造化した値はログでは null
    for key in ("threshold_pct", "peak_value", "peak_at_utc", "sample_count", "continues_from_before"):
        assert item["ref"][key] is None
    assert sum(b["log_error"] for b in data["overview"]) == 1


@pytest.mark.asyncio
async def test_log_only_error_or_above_regardless_of_case(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _logs(
        vid,
        (1, "info", "i"), (2, "warning", "w"), (3, None, "none"), (4, "debug", "d"), (5, "", "empty"),
        (6, "ERROR", "upper", {"log_kind": "k6"}),
        (7, " Critical ", "spaced", {"log_kind": "k7"}),
        (8, "fatal", "fatal", {"log_kind": "k8"}),
        (9, "panic", "panic", {"log_kind": "k9"}),
        (10, "errors-ish", "not exact", {"log_kind": "k10"}),
    )
    data = await _post(client)
    assert [(i["detail"], i["level"]) for i in _log_items(data)] == [
        ("upper", "warning"), ("spaced", "error"), ("fatal", "error"), ("panic", "error"),
    ]
    assert sum(b["log_error"] for b in data["overview"]) == 4


@pytest.mark.asyncio
async def test_log_consecutive_same_source_is_merged_with_count(client: AsyncClient) -> None:
    vid = await _vcenter()
    ids = await _logs(
        vid,
        (1, "error", "first"),
        (2, "Error", "second"),
        (3, "err", "third"),
        (3.5, "critical", "worse"),  # level が違う（悪化した時点）ので別の行
        (4, "error", "other kind", {"log_kind": "hostd"}),
        (5, "error", "other host", {"host": "esx02.example.com"}),
        (6, "error", "again"),
        (12, "error", "after a 6 minute gap"),  # 間隔の上限（5 分）を超える
    )
    data = await _post(client)
    got = [(i["title"], i["count"], i["detail"]) for i in _log_items(data)]
    assert got == [
        ("esx01.example.com vmkernel", 3, "first"),
        ("esx01.example.com vmkernel", 1, "worse"),
        ("esx01.example.com hostd", 1, "other kind"),
        ("esx02.example.com vmkernel", 1, "other host"),
        ("esx01.example.com vmkernel", 1, "again"),
        ("esx01.example.com vmkernel", 1, "after a 6 minute gap"),
    ]
    first = _log_items(data)[0]
    assert first["ref"]["log_id"] == ids[0]
    assert _dt(first["end_utc"]) == _at(3)
    # 俯瞰はまとめる前の件数
    assert sum(b["log_error"] for b in data["overview"]) == 8


@pytest.mark.asyncio
async def test_log_uses_effective_at_and_half_open_period(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _logs(
        vid,
        (0, "error", "at from", {"log_kind": "a"}),
        (30, "error", "occurred_at differs", {"log_kind": "b", "occurred_at": _at(-30)}),
        (120, "error", "at to", {"log_kind": "c"}),
    )
    items = _log_items(await _post(client))
    assert [(i["detail"], _dt(i["timestamp_utc"])) for i in items] == [
        ("at from", _at(0)),
        ("occurred_at differs", _at(30)),
    ]


@pytest.mark.asyncio
async def test_log_detail_is_read_only_for_kept_items_and_truncated(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    vid = await _vcenter()
    long_message = "x" * 1500
    earliest, merged_first, _merged_second, _far = await _logs(
        vid,
        (1, "error", "earliest", {"log_kind": "a"}),
        (60, "error", long_message, {"log_kind": "b"}),
        (61, "error", "merged-second", {"log_kind": "b"}),
        (90, "error", "far", {"log_kind": "c"}),
    )
    captured: list = []
    original = AsyncSession.execute

    async def spy(self, statement, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(statement)
        return await original(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", spy)
    data = await _post(client, item_limit=1, anchor="2026-03-22T01:00:30Z")
    monkeypatch.setattr(AsyncSession, "execute", original)

    (item,) = _log_items(data)
    assert item["count"] == 2
    assert item["detail"] == "x" * 1000 + "…"
    signal = data["highlights"]["first_signal"]
    assert signal["kind"] == "log" and signal["detail"] == "earliest"
    sql = [str(s) for s in captured]
    list_sql = [s for s in sql if "SELECT log_records.id, log_records.effective_at" in s]
    assert list_sql and all("log_records.message" not in s for s in list_sql)
    # message を引くのは、残った行（まとめた行は最初のログ）と first_signal の id だけ
    assert _message_fetch_ids(captured, "log_records") == {merged_first, earliest}


@pytest.mark.asyncio
async def test_log_entity_filter_uses_host_and_vcenter_filter(client: AsyncClient) -> None:
    v1 = await _vcenter("vc-l1")
    v2 = await _vcenter("vc-l2")
    await _logs(v1, (1, "error", "a", {"host": "ESX-Alpha.example.com"}), (2, "error", "b", {"host": "esx-beta"}))
    await _logs(v2, (3, "error", "c", {"host": "esx-alpha-2"}))
    assert [i["detail"] for i in _log_items(await _post(client, entity="alpha"))] == ["a", "c"]
    data = await _post(client, entity="alpha", vcenter_id=str(v2))
    assert [i["detail"] for i in _log_items(data)] == ["c"]
    assert sum(b["log_error"] for b in data["overview"]) == 1
    # LIKE のワイルドカードは文字として扱う
    assert _log_items(await _post(client, entity="esx_")) == []


@pytest.mark.asyncio
async def test_log_overview_counts_per_bucket(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _logs(vid, (1, "error", "a"), (1.5, "error", "b"), (3, "error", "c"), (3, "info", "skip"))
    data = await _post(client)
    assert [b["log_error"] for b in data["overview"]][:4] == [0, 2, 0, 1]


@pytest.mark.asyncio
async def test_log_is_kept_after_alert_event_and_metric_when_truncating(client: AsyncClient) -> None:
    vid = await _vcenter()
    # critical のログは level error。同じ level のアラート・イベント・メトリクスより後に回る（最も新しくても）
    await _logs(vid, *[(50 + i, "critical", f"log-{i}", {"log_kind": f"k{i}"}) for i in range(5)])
    await _series(vid, "host-1", [(10, 96)])
    await _events(vid, (20, "E", "h1", 65))
    async with session_scope() as session:
        rule = AlertRule(name="r-err", rule_type="event_score", alert_level="error", config={})
        session.add(rule)
        await session.flush()
        session.add(
            AlertHistory(
                rule_id=rule.id, alert_level="error", state="firing",
                context_key="X", notified_at=_at(5), channel="none",
            )
        )
    data = await _post(client, item_limit=3)
    assert data["truncated"] is True and data["total_items"] == 8
    assert [i["kind"] for i in data["items"]] == ["alert", "metric", "event"]
    data = await _post(client, item_limit=4)
    assert [i["kind"] for i in data["items"]] == ["alert", "metric", "event", "log"]
    # anchor があるときは距離が優先
    data = await _post(client, item_limit=1, anchor="2026-03-22T00:52:00Z")
    assert [i["detail"] for i in data["items"]] == ["log-2"]


@pytest.mark.asyncio
async def test_plain_error_logs_do_not_push_out_warning_metric_intervals(client: AsyncClient) -> None:
    """通常の error ログ（level warning）が大量にあっても、warning の超過区間は残る。"""
    vid = await _vcenter()
    await _logs(vid, *[(30 + i * 0.1, "error", f"log-{i}", {"log_kind": f"k{i}"}) for i in range(20)])
    await _series(vid, "host-1", [(10, 85)])
    data = await _post(client, item_limit=1)
    assert [(i["kind"], i["level"]) for i in data["items"]] == [("metric", "warning")]


@pytest.mark.asyncio
async def test_log_with_error_is_first_signal(client: AsyncClient) -> None:
    vid = await _vcenter()
    (log_id,) = await _logs(vid, (1, "error", "early failure"))
    await _events(vid, (5, "Warn", "h2", 45))
    signal = (await _post(client))["highlights"]["first_signal"]
    assert signal["id"] == f"log:{log_id}"
    assert signal["detail"] == "early failure"


@pytest.mark.asyncio
async def test_log_source_only_issues_log_queries(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    vid = await _vcenter()
    await _logs(vid, (1, "error", "a"))
    await _events(vid, (2, "A", "h1", 30))
    await _series(vid, "host-1", [(3, 90)])
    captured: list[str] = []
    original = AsyncSession.execute

    async def spy(self, statement, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(str(statement))
        return await original(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", spy)
    data = await _post(client, sources=["log"])
    monkeypatch.setattr(AsyncSession, "execute", original)
    assert [i["kind"] for i in data["items"]] == ["log"]
    assert captured and all("log_records" in s or "vcenters" in s for s in captured)
    assert data["highlights"]["new_event_types"] == []
    for b in data["overview"]:
        assert (b["event_total"], b["event_notable"], b["alert"], b["metric_breach"]) == (0, 0, 0, 0)


def test_disk_and_network_thresholds_are_documented_as_unused() -> None:
    """互換のために受け取るが使わない。スキーマの説明にその旨と理由を書く。"""
    fields = IncidentTimelineViewRequest.model_fields
    for name in ("metric_threshold_disk_pct", "metric_threshold_network_pct"):
        description = fields[name].description or ""
        assert "使わない" in description and "KB/s" in description


# --- 行数の上限: ログ・メトリクスは省いて返す ----------------------------------------------
#
# イベントとアラートは上限を超えると 422。ログとメトリクスの超過区間は、その種別の行だけを省き、
# omitted_sources で伝える（ほかの種別は返す）。


async def _one_firing_alert(minute: float = 3) -> int:
    return await _alert_history("event_score", "SomeEvent", minute, name=f"r-omit-{minute}")


@pytest.mark.asyncio
async def test_too_many_log_rows_omits_only_logs(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    vid = await _vcenter()
    await _logs(vid, (1, "error", "a"), (2, "critical", "b", {"log_kind": "k2"}), (3, "info", "not counted"))
    await _events(vid, (4, "A", "h1", 50))
    alert_id = await _one_firing_alert(5)
    monkeypatch.setattr(require_settings(), "context_aggregation_max_rows", 1)
    data = await _post(client)
    assert data["omitted_sources"] == [{"source": "log", "reason": "too_many_rows"}]
    assert [i["kind"] for i in data["items"]] == ["event", "alert"]
    assert data["items"][1]["id"] == f"alert:{alert_id}"
    # 俯瞰の件数（GROUP BY）はそのまま返す
    assert sum(b["log_error"] for b in data["overview"]) == 2
    # ハイライトは省いた種別を除いて求める（ログが最も早いが first_signal にならない）
    assert data["highlights"]["first_signal"]["kind"] == "event"
    assert all(t["entity_name"] != "esx01.example.com" for t in data["highlights"]["top_entities"])
    assert data["total_items"] == 2
    # error 未満の行は数えない（上限ちょうどなら省かない）
    monkeypatch.setattr(require_settings(), "context_aggregation_max_rows", 2)
    data = await _post(client)
    assert data["omitted_sources"] == []
    assert len(_log_items(data)) == 2


@pytest.mark.asyncio
async def test_too_many_metric_intervals_omits_only_metrics(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    vid = await _vcenter()
    await _series(vid, "host-1", [(0, 90), (5, 10), (10, 90)])
    await _events(vid, (4, "A", "h1", 50))
    monkeypatch.setattr(require_settings(), "context_aggregation_max_rows", 1)
    data = await _post(client)
    assert data["omitted_sources"] == [{"source": "metric", "reason": "too_many_rows"}]
    assert [i["kind"] for i in data["items"]] == ["event"]
    # 区間を作れないので俯瞰も数えられない（0 ではなく「分からない」ことは omitted_sources で伝える）
    assert sum(b["metric_breach"] for b in data["overview"]) == 0
    # 区間の数で数える（サンプル数ではない）
    monkeypatch.setattr(require_settings(), "context_aggregation_max_rows", 2)
    data = await _post(client)
    assert data["omitted_sources"] == [] and len(_metrics(data)) == 2


@pytest.mark.asyncio
async def test_both_logs_and_metrics_over_the_limit_are_omitted(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    vid = await _vcenter()
    await _series(vid, "host-1", [(0, 90), (5, 10), (10, 90)])
    await _logs(vid, (1, "error", "a"), (2, "error", "b", {"log_kind": "k2"}))
    await _one_firing_alert()
    monkeypatch.setattr(require_settings(), "context_aggregation_max_rows", 1)
    data = await _post(client)
    assert data["omitted_sources"] == [
        {"source": "metric", "reason": "too_many_rows"},
        {"source": "log", "reason": "too_many_rows"},
    ]
    assert [i["kind"] for i in data["items"]] == ["alert"]
    # sources に無い種別は omitted_sources に入らない
    data = await _post(client, sources=["alert", "log"])
    assert data["omitted_sources"] == [{"source": "log", "reason": "too_many_rows"}]
    data = await _post(client, sources=["alert"])
    assert data["omitted_sources"] == []


@pytest.mark.asyncio
async def test_events_and_alerts_over_the_limit_are_still_422(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    vid = await _vcenter()
    await _events(vid, (1, "A", "h1", 30), (2, "B", "h2", 30))
    monkeypatch.setattr(require_settings(), "context_aggregation_max_rows", 1)
    r = await client.post(URL, json=_body())
    assert r.status_code == 422
    assert "vCenter を指定" in r.json()["detail"]


@pytest.mark.asyncio
async def test_many_critical_logs_do_not_push_metric_intervals_out_of_a_24h_view(client: AsyncClient) -> None:
    """計測の条件（critical のログが 1 日 871 件。level は error）でも、warning の超過区間は一覧に残る。

    anchor が無いときは、ほかの種別があるかぎり枠（item_limit 既定 500）の 4 分の 1 をそれらに残す。
    """
    vid = await _vcenter()
    await _logs(
        vid,
        *[(i * 1440 / 871, "critical", f"crit-{i}", {"host": f"esx{i:03d}.example.com"}) for i in range(871)],
    )
    for n in range(60):
        await _series(vid, f"host-{n}", [(n * 20, 85)], name=f"esx-m{n:02d}")
    data = await _post(client, **{"to": "2026-03-23T00:00:00Z"})
    kinds = [i["kind"] for i in data["items"]]
    assert data["truncated"] is True and data["total_items"] == 871 + 60
    assert len(kinds) == 500
    assert kinds.count("metric") == 60
    assert kinds.count("log") == 440  # ほかの種別で埋まらない分はログで埋める
    # 超過区間が多いときは、4 分の 1（125 件）を超過区間に残し、重いログが残りを占める
    for n in range(60, 400):
        await _series(vid, f"host-{n}", [(n * 3.5, 85)], name=f"esx-m{n:03d}")
    data = await _post(client, **{"to": "2026-03-23T00:00:00Z"})
    kinds = [i["kind"] for i in data["items"]]
    assert kinds.count("log") == 375 and kinds.count("metric") == 125


# --- 期間の終わりで続いている超過（continues_after）と、moid で表示した行の絞り込み -----------
#
# continues_after: その系列の期間内の最後のサンプルが閾値以上で、それが期間の終わり（to。to が未来なら
# 現在時刻）から間隔の上限（既定 15 分）以内にあるとき真。期間の後ろのサンプルは読まない。


@pytest.mark.asyncio
async def test_metric_interval_continuing_at_the_end_of_the_period(client: AsyncClient) -> None:
    """レビューの例: 01:55 に 90%、to（02:00）ちょうどに 95%（期間外）。最後に見えたサンプルが超過中。"""
    vid = await _vcenter()
    await _series(vid, "host-1", [(115, 90), (120, 95)])
    (item,) = _metrics(await _post(client))
    assert _span(item) == (_at(115), None)
    assert item["ref"]["continues_after"] is True
    assert item["ref"]["continues_from_before"] is False
    assert item["detail"] == "ピーク 90%、サンプル 1 件、期間の終わりでも継続"


@pytest.mark.asyncio
async def test_metric_interval_ending_before_the_end_is_not_continuing(client: AsyncClient) -> None:
    vid = await _vcenter()
    # host-1: 期間の終わりの手前で閾値未満に下がった
    await _series(vid, "host-1", [(100, 90), (105, 91), (110, 50)])
    # host-2: 超過のまま、期間の終わりの 16 分前でサンプルが途絶えた（間隔の上限 15 分を超える）
    await _series(vid, "host-2", [(100, 90), (104, 92)], name="esx02")
    # host-3: 期間の終わりのちょうど 15 分前が最後（上限ちょうどは続いているとみなす）
    await _series(vid, "host-3", [(100, 90), (105, 92)], name="esx03")
    # host-4: 後の区間（110 分〜）は続いているが、前の区間（100 分）は終わっている
    await _series(vid, "host-4", [(100, 90), (105, 50), (110, 90), (115, 90)], name="esx04")
    items = _metrics(await _post(client))
    got = {(i["ref"]["entity_moid"], _dt(i["timestamp_utc"])): i["ref"]["continues_after"] for i in items}
    assert got == {
        ("host-1", _at(100)): False,
        ("host-2", _at(100)): False,
        ("host-3", _at(100)): True,
        ("host-4", _at(100)): False,
        ("host-4", _at(110)): True,
    }
    assert all("期間の終わり" not in i["detail"] for i in items if not i["ref"]["continues_after"])


@pytest.mark.asyncio
async def test_metric_interval_continuing_before_and_after_the_period(client: AsyncClient) -> None:
    vid = await _vcenter()
    await _series(vid, "host-1", [(-5, 90), *[(m, 90 + m / 100) for m in range(0, 120, 5)]])
    (item,) = _metrics(await _post(client))
    assert (item["ref"]["continues_from_before"], item["ref"]["continues_after"]) == (True, True)
    assert item["detail"] == "ピーク 91.15%、サンプル 24 件、期間の開始前から継続、期間の終わりでも継続"


@pytest.mark.asyncio
async def test_metric_continues_after_uses_now_when_the_period_ends_in_the_future(client: AsyncClient) -> None:
    """to が未来なら、まだ来ていないサンプルの分は途絶えとみなさない（現在時刻から測る）。"""
    vid = await _vcenter()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    async with session_scope() as session:
        session.add(
            MetricSample(
                vcenter_id=vid, sampled_at=now - timedelta(minutes=2), entity_type="HostSystem",
                entity_moid="host-1", entity_name="esx01", metric_key=CPU, value=90,
            )
        )
    body = {"from": (now - timedelta(hours=1)).isoformat(), "to": (now + timedelta(hours=1)).isoformat()}
    r = await client.post(URL, json=body)
    assert r.status_code == 200, r.text
    (item,) = _metrics(r.json())
    assert item["ref"]["continues_after"] is True


@pytest.mark.asyncio
async def test_metric_row_shown_by_moid_is_kept_when_filtering_by_its_entity_name(client: AsyncClient) -> None:
    """行の entity_name をそのまま entity に渡すと、その行が返る（名前のある系列も、無い系列も）。"""
    vid = await _vcenter()
    await _series(vid, "host-77", [(0, 90)], name="")
    await _series(vid, "host-78", [(0, 90)], name="   ")
    await _series(vid, "host-1", [(0, 90)], name="esx-named")
    items = _metrics(await _post(client))
    assert sorted(i["entity_name"] for i in items) == ["esx-named", "host-77", "host-78"]
    for item in items:
        filtered = _metrics(await _post(client, entity=item["entity_name"]))
        assert [i["id"] for i in filtered] == [item["id"]]
