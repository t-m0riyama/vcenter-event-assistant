"""タイムラインの構成変更の判定・表示・出力を確かめる。"""

from __future__ import annotations

import csv
import io
import itertools
import json
import os
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from zipfile import ZipFile

import pytest
from httpx import AsyncClient
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from vcenter_event_assistant_plugin_api import limits

from vcenter_event_assistant.api.schemas.incident_timeline_view import (
    IncidentTimelineViewRequest,
    IncidentTimelineViewResponse,
)
from vcenter_event_assistant.db.base import Base
from vcenter_event_assistant.db.models import (
    EventRecord,
    IncidentTimelineManualSnapshot,
    InventoryConfigDiff,
    InventorySyncState,
    LogRecord,
    VCenter,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.incident_timeline_view import build_incident_timeline_view

pytestmark = pytest.mark.asyncio

START = datetime(2026, 3, 22, tzinfo=timezone.utc)
END = START + timedelta(hours=2)
VIEW = "/api/incident-timeline/view"
SNAPSHOTS = "/api/incident-timeline/snapshots/manual"
VM = "vim.event.VmReconfiguredEvent"
ENTER = "vim.event.EnteredMaintenanceModeEvent"
EXIT = "vim.event.ExitMaintenanceModeEvent"
HOST = "vim.event.HostAddedEvent"
ROLE = "vim.event.RoleAddedEvent"
TASK_ROLE = "task.success.AuthorizationManager.addRole"
TASK_HOST = "task.success.ClusterComputeResource.addHost"
EVENTS = "builtin.vcenter.events"
TASKS = "builtin.vcenter.tasks"
KEYS = itertools.count(1)


async def test_config_change_definitions() -> None:
    from vcenter_event_assistant.rules.config_changes import (
        CONFIG_CHANGE_DEFINITIONS,
        CONFIG_CHANGE_EVENT_TYPES,
        config_change_kind,
    )

    assert len(CONFIG_CHANGE_DEFINITIONS) == 12
    events = [event for definition in CONFIG_CHANGE_DEFINITIONS for event in definition.event_types]
    tasks = [
        f"task.success.{operation}"
        for definition in CONFIG_CHANGE_DEFINITIONS
        for operation in definition.task_operations
    ]
    assert len(events) == 55
    assert len(tasks) == 69
    assert len(set(events + tasks)) == 124
    assert CONFIG_CHANGE_EVENT_TYPES == set(events + tasks)
    assert all(len(task) <= limits.MAX_EVENT_TYPE for task in tasks)
    assert config_change_kind(VM) == "vm_reconfigure"
    assert config_change_kind(ENTER) == "maintenance_enter"
    assert config_change_kind(EXIT) == "maintenance_exit"
    assert config_change_kind(TASK_ROLE) == "permission"
    assert config_change_kind("task.success.host.ServiceSystem.start") == "host_config"
    for unknown in (
        "VmReconfiguredEvent",
        VM + "Extra",
        VM.lower(),
        "task.failed.AuthorizationManager.addRole",
        "task.success.VirtualMachine.reconfigVm",
        "vim.event.HostDasEnabledEvent",
    ):
        assert config_change_kind(unknown) is None


def _time(minute: float) -> datetime:
    return START + timedelta(minutes=minute)


def _request(**options: object) -> dict:
    return {"from": START.isoformat(), "to": END.isoformat(), "sources": ["event"], **options}


def _vc(name: str = "vc-demo") -> VCenter:
    return VCenter(id=uuid.uuid4(), name=name, host="h", port=443, username="u", password="p")


def _event(
    vc: VCenter, minute: float, event_type: str, entity: str | None, score: int = 0, **extra: object
) -> EventRecord:
    return EventRecord(
        vcenter_id=vc.id,
        occurred_at=_time(minute),
        event_type=event_type,
        entity_name=entity,
        notable_score=score,
        vmware_key=next(KEYS),
        message="イベントの詳細",
        **extra,
    )


def _log(vc: VCenter, minute: float, host: str) -> LogRecord:
    return LogRecord(
        vcenter_id=vc.id, collector_id="test.logs", source_id="test", host=host,
        log_kind="vmkernel", file_generation="g1", byte_offset=next(KEYS),
        effective_at=_time(minute), collected_at=_time(minute), severity="error", message="error",
    )


async def _save(*rows: VCenter | EventRecord | LogRecord) -> None:
    async with session_scope() as db:
        db.add_all(rows)
        await db.flush()


async def _view(client: AsyncClient, **options: object) -> dict:
    response = await client.post(VIEW, json=_request(**options))
    assert response.status_code == 200, response.text
    return response.json()


def _ids(result: dict) -> list[int]:
    return [item["ref"]["event_id"] for item in result["items"] if item["kind"] == "event"]


@pytest.mark.parametrize("dialect", ["sqlite", "postgres"])
async def test_config_change_window_and_filters(client: AsyncClient, config_db, dialect: str) -> None:
    vc, other = _vc(), _vc("other")
    early = _event(vc, 1, VM, "web", entity_moid="vm-1")
    fraction = _event(vc, 10, ENTER, "web", entity_moid="vm-1")
    fraction.occurred_at += timedelta(microseconds=999)
    boundary = _event(vc, 10, VM, "web", entity_moid="vm-1")
    boundary.occurred_at += timedelta(milliseconds=1)
    later = _event(vc, 11, VM, "web", 10, entity_moid="vm-1")
    wrong_target = _event(vc, 2, VM, "web", entity_moid="vm-2")
    wrong_vcenter = _event(other, 3, VM, "web", entity_moid="vm-1")
    end = _event(vc, 120, EXIT, "web", entity_moid="vm-1")
    rows = (vc, other, early, fraction, boundary, later, wrong_target, wrong_vcenter, end)
    options = dict(anchor=_time(10).isoformat(), entity="web", entity_moid="vm-1", vcenter_id=str(vc.id))
    if dialect == "postgres":
        config_db.add_all([vc, other])
        await config_db.flush()
        config_db.add_all(rows[2:])
        await config_db.commit()
        request = IncidentTimelineViewRequest.model_validate(_request(**options))
        result = (await build_incident_timeline_view(config_db, request, owner_key="config-change")).model_dump()
    else:
        await _save(*rows)
        result = await _view(client, **options)
        empty = await _view(client, anchor=(START - timedelta(microseconds=1)).isoformat())
        assert empty["highlights"]["config_changes"] == []
        assert _ids(empty) == [later.id]
        assert (await _view(client, sources=["log"]))["highlights"]["config_changes"] is None
        assert _ids(await _view(client, entity="WEB", vcenter_id=str(vc.id))) == [
            early.id, wrong_target.id, fraction.id, boundary.id, later.id
        ]

    assert _ids(result) == [early.id, fraction.id, later.id]
    assert [item["config_change_kind"] for item in result["items"]] == [
        "vm_reconfigure", "maintenance_enter", "vm_reconfigure"
    ]
    assert all(item["detail"] == "イベントの詳細" for item in result["items"])
    assert all(not {"user_name", "chain_id", "collector_id"} & item.keys() for item in result["items"])
    assert [card["event_ids"] for card in result["highlights"]["config_changes"]] == [[fraction.id], [early.id]]
    assert result["highlights"]["config_changes"][0]["vcenter_name"] == "vc-demo"


async def test_config_change_keeps_ordinary_merging_and_highlights(client: AsyncClient) -> None:
    vc = _vc()
    error = _event(vc, 30, VM, "scored", 10)
    logs = [_log(vc, 10, "host"), _log(vc, 12, "host")]
    await _save(vc, error)
    await _save(*logs)
    options = dict(sources=["event", "log"])
    before = await _view(client, **options)
    low = _event(vc, 31, VM, "scored")
    between_logs = _event(vc, 11, EXIT, "maintenance-only", severity="warning")
    before_logs = _event(vc, 8, ENTER, "maintenance-only", severity="warning")
    await _save(low, between_logs, before_logs)
    after = await _view(client, **options)

    assert _ids(after) == [before_logs.id, between_logs.id, error.id, low.id]
    assert [row for row in after["items"] if row["kind"] == "log"] == [
        row for row in before["items"] if row["kind"] == "log"
    ]
    assert next(row for row in after["items"] if row["kind"] == "log")["count"] == 2
    assert after["total_items"] == before["total_items"] == 2
    for field in ("top_entities", "new_event_types", "first_signal"):
        assert after["highlights"][field] == before["highlights"][field]
    assert sum(row["event_total"] for row in after["overview"]) == 4
    assert sum(row["event_notable"] for row in after["overview"]) == 1
    assert sum(row["log_error"] for row in after["overview"]) == 2
    vm_card = after["highlights"]["config_changes"][0]
    assert vm_card["event_ids"] == [error.id, low.id]


@pytest.mark.parametrize("item_limit", [3, 60])
async def test_config_change_item_budget_preserves_error_and_keeps_cards(client: AsyncClient, item_limit: int) -> None:
    vc = _vc()
    error = _event(vc, 61, "vim.event.HostConnectionLostEvent", "error-host", 60)
    await _save(vc, error)
    options = dict(item_limit=item_limit, anchor=_time(60).isoformat())
    before = await _view(client, **options)
    rows = [_event(vc, 50 + i / 10, VM, f"vm-{i}") for i in range(55)]
    await _save(*rows)
    after = await _view(client, **options)
    budget = min(50, item_limit)
    assert _ids(after) == [*(row.id for row in rows[-budget:]), error.id]
    assert after["total_items"] == before["total_items"] == 1
    assert after["truncated"] is False
    assert after["config_change_items_total"] == 55
    assert after["config_change_items_shown"] == budget
    assert after["config_change_items_truncated"] is True
    highlights = after["highlights"]
    assert highlights["config_changes_total"] == 55
    assert highlights["config_change_counts"] == {"vm_reconfigure": 55}
    assert [card["event_ids"] for card in highlights["config_changes"]] == [
        [row.id] for row in reversed(rows[-20:])
    ]


async def test_config_change_without_anchor_preserves_log_budget(client: AsyncClient) -> None:
    vc = _vc()
    await _save(vc)
    await _save(*(_log(vc, i, f"host-{i}") for i in range(30)))
    options = dict(sources=["log", "event"], item_limit=5)
    before = await _view(client, **options)
    await _save(*(_event(vc, 60 + i, VM, f"vm-{i}") for i in range(10)))
    after = await _view(client, **options)
    assert [row for row in after["items"] if row["kind"] == "log"] == before["items"]
    assert len(before["items"]) == 5
    assert after["truncated"] is True
    assert after["total_items"] == before["total_items"]
    assert len(_ids(after)) == 5
    assert after["config_change_items_total"] == 10
    assert after["config_change_items_shown"] == 5
    assert after["config_change_items_truncated"] is True


async def test_config_change_raw_limit_uses_newest_rows_without_422(client: AsyncClient) -> None:
    vc = _vc()
    rows = [_event(vc, 1, EXIT, "oldest")] + [
        _event(vc, 10 + i / 100, VM, "vm") for i in range(2000)
    ]
    await _save(vc, *rows)
    after = await _view(client)
    highlights = after["highlights"]
    assert highlights["config_changes_truncated"] is True
    assert highlights["config_changes_total"] == 1
    assert highlights["config_change_counts"] == {"vm_reconfigure": 1}
    (card,) = highlights["config_changes"]
    assert card["event_count"] == 2000
    assert card["event_ids"] == [row.id for row in rows[1:21]]
    assert after["config_change_items_total"] == 1
    assert after["config_change_items_shown"] == 1
    (item,) = after["items"]
    assert item["count"] == 2000


async def test_config_change_truncated_cards_use_same_start_for_scored_events(client: AsyncClient) -> None:
    vc = _vc()
    older = _event(vc, 9, EXIT, "older", 40)
    at_start = _event(vc, 10, ENTER, "at-start", 40)
    newer = _event(vc, 40, ROLE, None, 40)
    await _save(
        vc, older, at_start, newer, _event(vc, 1, EXIT, "oldest"),
        *(_event(vc, 10 + i / 100, VM, "vm") for i in range(2000)),
    )
    result = await _view(client)
    highlights = result["highlights"]
    assert highlights["config_changes_truncated"] is True
    assert [card["kind"] for card in highlights["config_changes"]] == [
        "permission", "vm_reconfigure", "maintenance_enter",
    ]
    assert highlights["config_changes"][-1]["event_ids"] == [at_start.id]
    assert older.id in _ids(result)


async def test_config_change_chain_target_and_vcenter_grouping(client: AsyncClient) -> None:
    vc, other = _vc(), _vc("other")
    task = _event(vc, 1, TASK_HOST, "cluster", chain_id=123, collector_id=TASKS,
                  entity_moid="domain-c1", entity_type="ClusterComputeResource")
    host = _event(vc, 30, HOST, "host", chain_id=123, collector_id=EVENTS, entity_moid="host-1")
    unrelated = _event(vc, 31, HOST, "other-host", chain_id=123, collector_id="plugin.events")
    moid_match = _event(vc, 34, HOST, "renamed", entity_moid="host-1")
    name_match = _event(vc, 39, HOST, "host")
    other_moid = _event(vc, 40, HOST, "second-host", entity_moid="host-2")
    expired = _event(vc, 45, HOST, "renamed", entity_moid="host-1")
    same_chain_other_kind = _event(vc, 32, VM, "host", chain_id=123, entity_moid="host-1")
    same_chain_other_vc = _event(other, 32, HOST, "host", chain_id=123, entity_moid="host-1")
    await _save(vc, other, task, host, unrelated, moid_match, name_match, other_moid, expired,
                same_chain_other_kind, same_chain_other_vc)

    highlights = (await _view(client))["highlights"]
    cards = {card["event_ids"][0]: card for card in highlights["config_changes"]}
    assert cards[task.id]["event_ids"] == [task.id, host.id, moid_match.id, name_match.id]
    assert cards[task.id]["entity_name"] == "cluster"
    assert cards[task.id]["entity_moid"] == "domain-c1"
    assert cards[task.id]["entity_type"] == "ClusterComputeResource"
    assert cards[task.id]["event_types"] == [TASK_HOST, HOST]
    assert {unrelated.id, expired.id, same_chain_other_kind.id, same_chain_other_vc.id} <= cards.keys()
    assert highlights["config_change_counts"] == {"inventory": 5, "vm_reconfigure": 1}
    assert list(highlights["config_change_counts"]) == ["vm_reconfigure", "inventory"]
    assert highlights["config_changes_total"] == sum(highlights["config_change_counts"].values())


async def test_config_change_uses_moid_when_both_rows_have_one(client: AsyncClient) -> None:
    vc = _vc()
    one = _event(vc, 1, VM, "same", entity_moid="vm-1")
    two = _event(vc, 2, VM, "same", entity_moid="vm-2")
    await _save(vc, one, two)
    cards = (await _view(client))["highlights"]["config_changes"]
    assert [card["event_ids"] for card in cards] == [[two.id], [one.id]]


@pytest.mark.parametrize("lookup_moid", ["vm-1", None])
async def test_config_change_prefers_moid_then_latest_name(
    client: AsyncClient, lookup_moid: str | None
) -> None:
    vc = _vc()
    exact = _event(vc, 1, VM, "same", entity_moid="vm-1", chain_id=1)
    named = _event(vc, 8, VM, "same", chain_id=2)
    exact_update = _event(vc, 9, VM, "same", entity_moid="vm-1", chain_id=1)
    named_update = _event(vc, 10, VM, "same", chain_id=2)
    lookup = _event(vc, 11, VM, "same", entity_moid=lookup_moid)
    await _save(vc, exact, named, exact_update, named_update, lookup)

    latest = (await _view(client))["highlights"]["config_changes"][0]
    expected = [exact, exact_update, lookup] if lookup_moid else [named, named_update, lookup]
    assert latest["event_ids"] == [row.id for row in expected]


async def test_config_change_falls_back_to_name_when_moid_match_is_stale(client: AsyncClient) -> None:
    vc = _vc()
    exact = _event(vc, 1, VM, "same", entity_moid="vm-1")
    named = _event(vc, 7, VM, "same")
    lookup = _event(vc, 8, VM, "same", entity_moid="vm-1")
    await _save(vc, exact, named, lookup)
    latest = (await _view(client))["highlights"]["config_changes"][0]
    assert latest["event_ids"] == [named.id, lookup.id]


async def test_config_change_without_target_groups_by_user(client: AsyncClient) -> None:
    vc = _vc()
    rows = [
        _event(vc, 1, ROLE, None, user_name="operator"),
        _event(vc, 2, ROLE, None),
        _event(vc, 3, TASK_ROLE, None, collector_id=TASKS, user_name="operator"),
        _event(vc, 4, ROLE, None),
        _event(vc, 5, ROLE, None, user_name="other"),
        _event(vc, 9, ROLE, None, user_name="operator"),
    ]
    await _save(vc, *rows)
    cards = (await _view(client))["highlights"]["config_changes"]
    assert [card["event_ids"] for card in cards] == [
        [rows[i].id for i in indexes] for indexes in ([5], [4], [3], [0, 2], [1])
    ]
    assert cards[3]["user_names"] == ["operator"]
    assert cards[3]["entity_name"] is None


async def test_config_change_ignores_empty_user_names(client: AsyncClient) -> None:
    vc = _vc()
    first = _event(vc, 1, ROLE, None, user_name="")
    second = _event(vc, 2, TASK_ROLE, None, user_name="", collector_id=TASKS)
    await _save(vc, first, second)
    cards = (await _view(client))["highlights"]["config_changes"]
    assert [card["event_ids"] for card in cards] == [[second.id], [first.id]]
    assert all(card["user_names"] == [] for card in cards)


async def test_config_change_card_caps_metadata_in_time_order(client: AsyncClient) -> None:
    vc = _vc()
    types = [
        "vim.event.PermissionAddedEvent", "vim.event.PermissionRemovedEvent",
        "vim.event.PermissionUpdatedEvent", ROLE, "vim.event.RoleRemovedEvent",
        "vim.event.RoleUpdatedEvent", TASK_ROLE,
    ]
    rows = [
        _event(vc, i, types[i % len(types)], None, chain_id=42, user_name=f"user-{i % 4}")
        for i in range(27)
    ]
    await _save(vc, *rows)
    (card,) = (await _view(client))["highlights"]["config_changes"]
    assert card["label"] == "権限とロールの変更"
    assert datetime.fromisoformat(card["first_utc"]) == START
    assert datetime.fromisoformat(card["last_utc"]) == _time(26)
    assert card["user_names"] == ["user-0", "user-1", "user-2"]
    assert card["event_types"] == types[:5]
    assert card["event_ids"] == [row.id for row in rows[:20]]
    assert card["event_count"] == 27


@pytest.fixture
async def config_db(dialect: str) -> AsyncIterator[AsyncSession]:
    if dialect == "postgres":
        url = os.environ.get("VEA_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("VEA_TEST_POSTGRES_URL must point to a dedicated test DB (schema is cleared)")
    else:
        url = "sqlite+aiosqlite:///:memory:"
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            if dialect == "postgres":
                await conn.execute(text("DROP SCHEMA public CASCADE"))
                await conn.execute(text("CREATE SCHEMA public"))
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.mark.parametrize("dialect", ["sqlite", "postgres"])
async def test_config_change_deduplicates_score_update(
    config_db: AsyncSession, monkeypatch: pytest.MonkeyPatch, dialect: str
) -> None:
    vc = _vc()
    row = _event(vc, 10, VM, "vm", 10)
    config_db.add(vc)
    await config_db.flush()
    config_db.add(row)
    await config_db.commit()
    execute = config_db.execute
    score_updated = False

    async def execute_and_update_score(statement, *args, **kwargs):
        nonlocal score_updated
        result = await execute(statement, *args, **kwargs)
        sql = str(statement)
        if not score_updated and "events.notable_score >=" in sql and "LIMIT" in sql:
            change = update(EventRecord).where(EventRecord.id == row.id).values(notable_score=0)
            if dialect == "postgres":
                # PostgreSQL では別トランザクションで再計算を確定する。
                async with AsyncSession(config_db.bind) as writer:
                    await writer.execute(change)
                    await writer.commit()
            else:
                # SQLite では同じトランザクションから更新し、両方の SELECT が同じ id を読むようにする。
                await execute(change)
            score_updated = True
        return result

    monkeypatch.setattr(config_db, "execute", execute_and_update_score)
    request = IncidentTimelineViewRequest.model_validate(_request())
    result = await build_incident_timeline_view(config_db, request, owner_key="config-change")
    assert score_updated
    (item,) = result.items
    assert item.id == f"event:{row.id}"
    assert item.score == 10
    assert result.config_change_items_total == 0
    assert result.config_change_items_truncated is False
    (card,) = result.highlights.config_changes
    assert card.event_ids == [row.id]
    assert card.event_count == 1


async def test_config_change_export_and_legacy_snapshot(viewer_client: AsyncClient) -> None:
    vc = _vc()
    await _save(
        vc, _event(vc, 1, VM, "earlier"),
        _event(vc, 2, VM, "vm|name", user_name="@operator\n[link](https://example.invalid)"),
    )
    response = await viewer_client.post(
        "/api/incident-timeline/export", params={"format": "zip"}, json=_request(item_limit=1)
    )
    assert response.status_code == 200, response.text
    with ZipFile(io.BytesIO(response.content)) as archive:
        report = archive.read("report.md").decode()
        assert "### 構成変更" in report
        assert "VM の構成変更" in report
        assert "vc-demo" in report
        assert "@operator" in report
        assert "\n[link]" not in report
        assert "構成変更の行は起点（または期間の終わり）に近い 1 件だけ" in report
        assert "一覧に表示した行は ZIP の items.csv にある" in report
        assert "打ち切った構成変更の行は CSV に含まれません" in report
        assert "種類ごとの件数: ` VM の構成変更 ` 2 件" in report
        assert "表示の上限を超えた件数: 0 件" in report
        assert "読み込み上限による打ち切り: なし" in report
        (row,) = csv.DictReader(io.StringIO(archive.read("items.csv").decode("utf-8-sig")))
        assert row["config_change_kind"] == "vm_reconfigure"
        result = json.loads(archive.read("result.json"))
        assert result["config_change_items_shown"] == 1
        assert result["highlights"]["config_changes"][0]["user_names"][0].startswith("@operator")

    sid = uuid.uuid4()
    async with session_scope() as session:
        session.add(IncidentTimelineManualSnapshot(
            id=sid, from_time=START, to_time=END, timestamp_utc=START,
            operator_note="以前に保存した結果",
            result_payload={
                "from_utc": START.isoformat(), "to_utc": END.isoformat(),
                "bucket_seconds": 60, "overview": [], "items": [
                    {"id": "event:1", "kind": "event", "timestamp_utc": START.isoformat(),
                     "level": "info", "title": "旧形式の行"}
                ], "total_items": 1, "truncated": False, "highlights": {},
            },
        ))
    detail = await viewer_client.get(f"{SNAPSHOTS}/{sid}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["has_result"] is True
    assert detail.json()["result"]["highlights"]["config_changes"] is None
    assert detail.json()["result"]["config_change_items_shown"] == 0
    assert detail.json()["result"]["items"][0]["config_change_kind"] is None
    exported = await viewer_client.get(f"{SNAPSHOTS}/{sid}/export", params={"format": "md"})
    assert exported.status_code == 200, exported.text
    assert "判定していません（この機能の前に保存した結果、または種別にイベントが無い）" in exported.text


def _diff(vc: VCenter, after: float, observed: float, **options: object) -> InventoryConfigDiff:
    return InventoryConfigDiff(**{
        "vcenter_id": vc.id, "moid": "vm-1", "category": "vm_config", "entity_type": "VirtualMachine",
        "entity_name": "guest", "attribute": "num_cpu", "old_value": "2", "new_value": "4",
        "truncated": False, "changed_after": _time(after), "observed_at": _time(observed), **options,
    })


@pytest.fixture
def config_clock(monkeypatch):
    from vcenter_event_assistant.services import incident_timeline_view
    from vcenter_event_assistant.settings_binding import require_settings

    monkeypatch.setattr(incident_timeline_view, "utcnow", lambda: END)
    settings = require_settings()
    monkeypatch.setattr(settings, "inventory_config_enabled", False)
    monkeypatch.setattr(settings, "inventory_config_retention_days", 1)


@pytest.mark.parametrize("dialect", ["sqlite", "postgres"])
async def test_config_diff_card_chain_and_strict_padded_overlap(config_db, dialect, config_clock):
    vc, other = _vc(), _vc("other")
    config_db.add_all([vc, other])
    await config_db.flush()
    first = _event(vc, 10, VM, "guest", entity_moid="vm-1", chain_id=12, collector_id=EVENTS)
    last = _event(
        vc, 20, "task.success.VirtualMachine.reconfigure", "another guest",
        entity_moid="vm-2", chain_id=12, collector_id=TASKS,
    )
    duplicate = _event(vc, 26, VM, "guest", entity_moid="vm-1", chain_id=13, collector_id=EVENTS)
    through_first = _diff(vc, 6, 8.5)
    through_last = _diff(vc, 21.5, 22.5, moid="vm-2")
    across_cards = _diff(vc, 9, 27)
    config_db.add_all([
        InventorySyncState(vcenter_id=vc.id, config_first_success_at=START),
        first, last, duplicate, across_cards, through_last, through_first,
        _diff(vc, 7, 8), _diff(vc, 22, 23, moid="vm-2"),
        _diff(vc, 10, 11, moid="vm-unrelated"), _diff(other, 10, 11),
    ])
    await config_db.flush()

    request = IncidentTimelineViewRequest.model_validate(_request())
    result = await build_incident_timeline_view(config_db, request, owner_key="config-diff")
    later, grouped = result.highlights.config_changes
    assert grouped.first_utc == _time(10)
    assert grouped.last_utc == _time(20)
    assert [diff.id for diff in grouped.diffs] == [through_first.id, through_last.id, across_cards.id]
    assert grouped.diffs_total == 3
    assert grouped.diffs_multiple_targets is True
    assert [diff.id for diff in later.diffs] == [across_cards.id]
    assert later.diffs_total == 1
    assert later.diffs_multiple_targets is False


@pytest.mark.parametrize("case", ["no_vcenter", "no_moid", "no_success", "before_success", "expired", "empty"])
@pytest.mark.parametrize("dialect", ["sqlite", "postgres"])
async def test_config_diff_card_availability(config_db, dialect, case, monkeypatch):
    from vcenter_event_assistant.services import incident_timeline_view as timeline

    vc = _vc()
    config_db.add(vc)
    await config_db.flush()
    first_success = {"no_success": None, "before_success": _time(11)}.get(case, START)
    config_db.add(InventorySyncState(vcenter_id=vc.id, config_first_success_at=first_success))
    if case != "empty":
        config_db.add(_diff(vc, 9, 11))
    await config_db.flush()
    entry = timeline.TimelineEntry(
        kind="event", source_id=1, timestamp_utc=_time(10), level="info", title=VM,
        vcenter_id=None if case == "no_vcenter" else vc.id, config_change_kind="vm_reconfigure",
        ref={} if case == "no_moid" else {"entity_moid": "vm-1"},
    )
    groups, _ = timeline._summarize_config_changes([entry])
    read_since = timeline.config_recorded_since
    calls = []

    def recorded_since(*args):
        calls.append(args)
        return read_since(*args)

    monkeypatch.setattr(timeline, "config_recorded_since", recorded_since)
    cut = _time(11 if case == "expired" else 10)
    (card,) = await timeline._attach_config_diffs(config_db, groups, retention_start=cut)
    assert card.diffs == ([] if case == "empty" else None)
    assert card.diffs_total == 0
    assert len(calls) == (0 if case in {"no_vcenter", "no_moid"} else 1)


@pytest.mark.parametrize("replacement", [False, True])
@pytest.mark.parametrize("dialect", ["sqlite", "postgres"])
async def test_config_diff_card_order_limit_and_pair(config_db, dialect, replacement, config_clock):
    vc = _vc()
    config_db.add(vc)
    await config_db.flush()
    early = _diff(vc, 9, 9.5, category="vm_config")
    category_first = _diff(vc, 9, 10, category="cluster_ha", element="z", attribute="enabled")
    attr_first = _diff(vc, 9, 10, element="a", attribute="capacity_kb")
    attr_next = [_diff(vc, 9, 10, element="a", attribute="uuid") for _ in range(2)]
    filler = [_diff(vc, 9, 10, element="b") for _ in range(4)]
    disk = dict(element="disk:2000", attribute=None)
    removed = _diff(vc, 9, 10, **disk, old_value='{"uuid":"old"}', new_value=None)
    added = _diff(vc, 9, 10, **disk, old_value=None, new_value='{"uuid":"new"}')
    tail = _diff(vc, 9, 10.5)
    diffs = [
        added, tail, *filler, *([removed] if replacement else []),
        *attr_next, attr_first, category_first, early,
    ]
    config_db.add_all([
        *diffs,
        InventorySyncState(vcenter_id=vc.id, config_first_success_at=START),
        _event(vc, 10, VM, "guest", entity_moid="vm-1"),
    ])
    await config_db.flush()
    request = IncidentTimelineViewRequest.model_validate(_request())
    result = await build_incident_timeline_view(config_db, request, owner_key="config-diff")
    (card,) = result.highlights.config_changes
    expected = [early, category_first, attr_first, *attr_next, *filler]
    if replacement:
        expected.append(removed)
    expected.append(added)
    assert [diff.id for diff in card.diffs] == [diff.id for diff in expected]
    assert card.diffs_total == len(diffs)


@pytest.mark.parametrize("dialect", ["sqlite", "postgres"])
async def test_config_diff_card_keeps_each_target_pair_together(config_db, dialect, config_clock):
    """複数の対象をまとめたカードで、同じ装置の入れ替わりが対象ごとに対のまま切れ目に掛かる。"""
    vc = _vc()
    config_db.add(vc)
    await config_db.flush()
    filler = [_diff(vc, 9, 9.5, element="b") for _ in range(8)]
    disk = dict(element="disk:2000", attribute=None)

    def replaced(moid: str) -> tuple[InventoryConfigDiff, InventoryConfigDiff]:
        return (
            _diff(vc, 9, 10, moid=moid, **disk, old_value='{"uuid":"old"}', new_value=None),
            _diff(vc, 9, 10, moid=moid, **disk, old_value=None, new_value='{"uuid":"new"}'),
        )

    removed_1, added_1 = replaced("vm-1")
    removed_2, added_2 = replaced("vm-2")
    config_db.add_all([
        InventorySyncState(vcenter_id=vc.id, config_first_success_at=START),
        _event(vc, 10, VM, "guest", entity_moid="vm-1", chain_id=12, collector_id=EVENTS),
        _event(
            vc, 20, "task.success.VirtualMachine.reconfigure", "another guest",
            entity_moid="vm-2", chain_id=12, collector_id=TASKS,
        ),
        *filler,
    ])
    await config_db.flush()
    # ID の順に頼らないよう、2 台目の「減った」行を先に入れる。
    for row in (removed_2, removed_1, added_2, added_1):
        config_db.add(row)
        await config_db.flush()

    request = IncidentTimelineViewRequest.model_validate(_request())
    result = await build_incident_timeline_view(config_db, request, owner_key="config-diff")
    (card,) = result.highlights.config_changes
    assert [diff.id for diff in card.diffs] == [diff.id for diff in (*filler, removed_1, added_1)]
    assert [(diff.vcenter_id, diff.entity_moid) for diff in card.diffs[-2:]] == [(vc.id, "vm-1")] * 2
    assert card.diffs_multiple_targets is False
    assert card.diffs_first_success_at == START
    assert card.diffs[-1].entity_name == added_1.entity_name
    assert card.diffs_total == 12


@pytest.mark.parametrize("remaining", [0, 2])
async def test_config_diff_report_remainder_and_safe_markdown(viewer_client, config_clock, remaining):
    vc = _vc()
    unsafe = "<img src=x>\n\u202e```[link](https://example.invalid)"
    async with session_scope() as session:
        session.add(vc)
        await session.flush()
        session.add_all([
            InventorySyncState(vcenter_id=vc.id, config_first_success_at=START),
            _event(vc, 10, VM, "guest", entity_moid="vm-1"),
            _diff(vc, 9, 10, element="nic:4000", element_label=unsafe, attribute="network",
                  old_value=json.dumps(unsafe), new_value=json.dumps("VM Network")),
            *[_diff(vc, 9, 10.5) for _ in range(8)],
            _diff(vc, 9, 11, element="disk:2000", attribute=None, old_value='{"uuid":"old"}', new_value=None),
            _diff(vc, 9, 11, element="disk:2000", attribute=None, old_value=None, new_value='{"uuid":"new"}'),
            *[_diff(vc, 9, 11.5) for _ in range(remaining)],
        ])

    response = await viewer_client.post(
        "/api/incident-timeline/export", params={"format": "zip"}, json=_request(),
    )
    assert response.status_code == 200, response.text
    with ZipFile(io.BytesIO(response.content)) as archive:
        report = archive.read("report.md").decode()
        section = report.split("### 構成変更\n")[1].split("### ")[0]
        assert "  - ` VM の構成 ` / ```` <img src=x> ```[link](https://example.invalid) ````" in section
        assert section.count("```` <img src=x> ```[link](https://example.invalid) ````") == 2
        assert "\u202e" not in section
        if remaining:
            assert f"  - ほか {remaining} 件" in section
        else:
            assert "  - ほか " not in section
        assert "追加" in section and "削除" in section
        assert "  - ` guest ` / " not in section
        assert "記録をやり直す前の値" not in section
        assert "2026/03/22 00:09:00 +00:00 から 2026/03/22 00:10:00 +00:00 の間" in section
        result = json.loads(archive.read("result.json"))
        (card,) = result["highlights"]["config_changes"]
        assert card["diffs_total"] == 11 + remaining
        assert len(card["diffs"]) == 11
        assert card["diffs"][0]["old_value"] == unsafe
        reader = csv.DictReader(io.StringIO(archive.read("items.csv").decode("utf-8-sig")))
        assert reader.fieldnames == [
            "timestamp", "timestamp_utc_offset", "kind_label", "level", "vcenter_name",
            "entity_name", "title", "detail", "count", "score", "id", "kind", "entity_type",
            "vcenter_id", "entity_moid", "end", "end_utc_offset", "event_id", "event_type",
            "alert_history_id", "alert_rule_id", "alert_rule_name", "alert_rule_type",
            "alert_state", "metric_key", "log_id", "threshold_pct", "peak_value", "peak_at",
            "peak_at_utc_offset", "sample_count", "continues_from_before", "continues_after",
            "time_zone", "config_change_kind",
        ]
        (row,) = reader
        assert unsafe not in row.values()


async def test_config_diff_report_shows_multiple_targets_and_pre_reset_note(viewer_client, config_clock):
    vc = _vc()
    unsafe = "<img src=x>\n\u202e```[link](https://example.invalid)"
    async with session_scope() as session:
        session.add(vc)
        await session.flush()
        session.add_all([
            InventorySyncState(vcenter_id=vc.id, config_first_success_at=_time(10)),
            _event(vc, 9, VM, "guest", entity_moid="vm-1", chain_id=12, collector_id=EVENTS),
            _event(vc, 11, VM, "another guest", entity_moid="vm-2", chain_id=12, collector_id=EVENTS),
            _diff(vc, 8, 9, entity_name=unsafe),
            _diff(vc, 9, 10, moid="vm-2", entity_name=""),
            _diff(vc, 10, 11, entity_name="guest"),
        ])
    response = await viewer_client.post(
        "/api/incident-timeline/export", params={"format": "md"}, json=_request(),
    )
    assert response.status_code == 200, response.text
    section = response.text.split("### 構成変更\n")[1].split("### ")[0]
    rows = [line for line in section.splitlines() if line.startswith("  - ")]
    assert len(rows) == 3
    assert rows[0].startswith("  - ```` <img src=x> ```[link](https://example.invalid) ```` / ` VM の構成 `")
    assert "\u202e" not in section
    assert rows[0].endswith(" 記録をやり直す前の値")
    assert rows[1].startswith("  - ` vm-2 ` / ` VM の構成 `")
    assert rows[2].startswith("  - ` guest ` / ` VM の構成 `")
    assert all("記録をやり直す前の値" not in row for row in rows[1:])


async def test_config_diff_snapshot_with_legacy_card_loads(viewer_client):
    sid = uuid.uuid4()
    async with session_scope() as session:
        session.add(IncidentTimelineManualSnapshot(
            id=sid, from_time=START, to_time=END, timestamp_utc=START, operator_note="保存済み",
            result_payload={
                "from_utc": START.isoformat(), "to_utc": END.isoformat(), "bucket_seconds": 60,
                "overview": [], "items": [], "total_items": 0, "truncated": False,
                "highlights": {"config_changes": [{
                    "kind": "vm_reconfigure", "label": "VM の構成変更",
                    "first_utc": START.isoformat(), "last_utc": START.isoformat(), "event_count": 1,
                }]},
            },
        ))
    response = await viewer_client.get(f"{SNAPSHOTS}/{sid}")
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["has_result"] is True
    (card,) = detail["result"]["highlights"]["config_changes"]
    assert card["diffs"] is None and card["diffs_total"] == 0
    assert card["event_count"] == 1

    report = await viewer_client.get(f"{SNAPSHOTS}/{sid}/export", params={"format": "md"})
    assert report.status_code == 200, report.text
    section = report.text.split("### 構成変更\n")[1].split("### ")[0]
    assert "- 2026/03/22 00:00:00 +00:00 / ` VM の構成変更 ` / - / - / - / 1 件" in section
    assert not any(line.startswith("  - ") for line in section.splitlines())


async def test_config_diff_snapshot_with_pr_c_diffs_loads(viewer_client):
    """PR C の JSON には差分の対象のキー自体が無い。"""
    at = START.isoformat()
    diff = {
        "id": 42, "category": "vm_config", "category_label": "VM の構成", "element": None,
        "element_label": None, "attribute": "num_cpu", "attribute_label": "CPU の数",
        "old_value": 2, "new_value": 4, "truncated": False, "changed_after": at, "observed_at": at,
    }
    raw = {
        "from_utc": at, "to_utc": END.isoformat(), "bucket_seconds": 60,
        "overview": [], "items": [], "total_items": 0, "truncated": False,
        "highlights": {"config_changes": [{
            "kind": "vm_reconfigure", "label": "VM の構成変更", "first_utc": at, "last_utc": at,
            "diffs": [diff], "diffs_total": 1,
        }]},
    }
    (card,) = IncidentTimelineViewResponse.model_validate(raw).highlights.config_changes
    (attached,) = card.diffs
    assert attached.vcenter_id is None and attached.entity_moid is None
    assert attached.old_value == 2 and attached.new_value == 4
    assert card.diffs_total == 1

    sid = uuid.uuid4()
    async with session_scope() as session:
        session.add(IncidentTimelineManualSnapshot(
            id=sid, from_time=START, to_time=END, timestamp_utc=START,
            operator_note="保存済み", result_payload=raw,
        ))
    response = await viewer_client.get(f"{SNAPSHOTS}/{sid}")
    assert response.status_code == 200, response.text
    assert response.json()["result"]["highlights"]["config_changes"][0] == card.model_dump(mode="json")


async def test_config_diff_values_stay_out_of_chat_and_digest_llm(monkeypatch, config_clock):
    from vcenter_event_assistant.services.chat import chat_llm
    from vcenter_event_assistant.services.digest import digest_llm
    from vcenter_event_assistant.services.digest.digest_run import run_digest_once
    from vcenter_event_assistant.settings_binding import require_settings

    value = "only-in-inventory-config-diff-5096"
    vc = _vc()
    async with session_scope() as session:
        session.add(vc)
        await session.flush()
        session.add_all([
            InventorySyncState(vcenter_id=vc.id, config_first_success_at=START),
            _event(vc, 10, VM, "guest", 80, entity_moid="vm-1"),
            _diff(vc, 9, 11, attribute="guest_id", new_value=json.dumps(value)),
        ])
        await session.flush()

        request = IncidentTimelineViewRequest.model_validate(_request())
        view = await build_incident_timeline_view(session, request, owner_key="config-diff")
        assert view.highlights.config_changes[0].diffs[0].new_value == value
        settings = require_settings()
        for name in ("chat", "digest"):
            monkeypatch.setattr(settings, f"llm_{name}_api_key", "test-key")
            monkeypatch.setattr(settings, f"llm_{name}_provider", "openai_compatible")
        monkeypatch.setattr(settings, "llm_anonymization_enabled", False)
        prompts = {}

        def capture(kind):
            async def receive(_model, messages, **_kwargs):
                prompts[kind] = json.dumps([message.content for message in messages], ensure_ascii=False)
                return "要約", None, None
            return receive

        for kind, module in (("chat", chat_llm), ("digest", digest_llm)):
            monkeypatch.setattr(module, "build_chat_model", lambda *args, **kwargs: object())
            monkeypatch.setattr(module, "stream_chat_to_text", capture(kind))
        from vcenter_event_assistant.api.schemas.chat import ChatRequest
        from vcenter_event_assistant.services.chat.chat_context_payloads import build_chat_context_payloads

        chat = ChatRequest.model_validate({
            "from": START.isoformat(), "to": END.isoformat(),
            "messages": [{"role": "user", "content": "構成変更を調べて"}],
        })
        payload = await build_chat_context_payloads(session, chat, owner_key="config-diff")
        await chat_llm.run_period_chat(
            context=payload.context, messages=chat.messages, period_metrics=payload.period_metrics,
            event_time_buckets=payload.event_time_buckets, incident_timeline=payload.incident_timeline,
            settings=settings,
        )
        await run_digest_once(session, kind="weekly", from_utc=START, to_utc=END, settings=settings)

    assert set(prompts) == {"chat", "digest"}
    assert all(VM in prompt and value not in prompt and '"diffs"' not in prompt for prompt in prompts.values())


@pytest.mark.parametrize("dialect_name", ["sqlite", "postgresql"])
async def test_config_diff_card_order_uses_binary_collation_in_sql(dialect_name):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from sqlalchemy.dialects import postgresql, sqlite

    from vcenter_event_assistant.services.inventory_config_diffs import read_config_diffs

    dialect = {"sqlite": sqlite.dialect(), "postgresql": postgresql.dialect()}[dialect_name]
    session = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=dialect),
        execute=AsyncMock(return_value=SimpleNamespace(all=list)),
    )
    await read_config_diffs(
        session, InventoryConfigDiff.vcenter_id == uuid.uuid4(),
        from_time=START, to_time=END, newest_first=False,
    )

    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=dialect))
    collation = '"C"' if dialect_name == "postgresql" else '"BINARY"'
    for column, suffix in [
        ("category", "ASC"), ("element", "ASC NULLS FIRST"), ("attribute", "ASC NULLS LAST"),
    ]:
        # 表示順だけでなく、ページ・切れ目・対の選択にも同じ並びを使う。
        assert sql.count(f"inventory_config_diffs.{column} COLLATE {collation} {suffix}") == 4


@pytest.mark.parametrize("dialect", ["sqlite", "postgres"])
async def test_config_diff_card_limit_preserves_cpu_and_memory(config_db, dialect, config_clock):
    vc = _vc()
    config_db.add(vc)
    await config_db.flush()
    devices = [_diff(vc, 9, 10, element=f"disk:{key:04d}", attribute="capacity_kb") for key in range(11)]
    cpu = _diff(vc, 9, 10)
    memory = _diff(vc, 9, 10, attribute="memory_mb", old_value="4096", new_value="8192")
    config_db.add_all([
        *devices, cpu, memory,
        InventorySyncState(vcenter_id=vc.id, config_first_success_at=START),
        _event(vc, 10, VM, "guest", entity_moid="vm-1"),
    ])
    await config_db.flush()

    request = IncidentTimelineViewRequest.model_validate(_request())
    result = await build_incident_timeline_view(config_db, request, owner_key="config-diff")
    (card,) = result.highlights.config_changes
    assert [diff.id for diff in card.diffs] == [diff.id for diff in [memory, cpu, *devices[:8]]]
    assert card.diffs_total == 13


@pytest.mark.parametrize("mismatch", ["observed_at", "moid", "category"])
@pytest.mark.parametrize("dialect", ["sqlite", "postgres"])
async def test_config_diff_card_pair_rejects_unrelated_addition(config_db, dialect, mismatch, config_clock):
    vc = _vc()
    config_db.add(vc)
    await config_db.flush()
    disk = dict(element="disk:2000", attribute=None)
    preceding = [_diff(vc, 8, 9) for _ in range(9)]
    removed = _diff(vc, 9, 10, **disk, old_value='{"uuid":"old"}', new_value=None)
    unrelated = _diff(
        vc, 9, 10.5 if mismatch == "observed_at" else 10,
        **disk, old_value=None, new_value='{"uuid":"other"}',
        moid="vm-2" if mismatch == "moid" else "vm-1",
        category="vm_other" if mismatch == "category" else "vm_config",
    )
    config_db.add_all([
        *preceding, removed, unrelated,
        InventorySyncState(vcenter_id=vc.id, config_first_success_at=START),
        _event(vc, 10, VM, "guest", entity_moid="vm-1", chain_id=12, collector_id=EVENTS),
        _event(vc, 10, VM, "another guest", entity_moid="vm-2", chain_id=12, collector_id=EVENTS),
    ])
    await config_db.flush()

    request = IncidentTimelineViewRequest.model_validate(_request())
    result = await build_incident_timeline_view(config_db, request, owner_key="config-diff")
    (card,) = result.highlights.config_changes
    assert [diff.id for diff in card.diffs] == [diff.id for diff in [*preceding, removed]]
    assert card.diffs_total == 11
