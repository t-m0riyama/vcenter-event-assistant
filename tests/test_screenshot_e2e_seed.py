"""``SCREENSHOT_E2E_SEED`` 時のドキュメント用 DB シード。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, func, select

from vcenter_event_assistant.db.models import (
    AlertHistory,
    AlertRule,
    DigestRecord,
    EventRecord,
    EventTypeGuide,
    LogPattern,
    LogPatternBackfillState,
    LogPatternBaseline,
    LogRecord,
    MetricSample,
    VCenter,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.dev.screenshot_e2e_seed import run_screenshot_e2e_seed_if_enabled
from vcenter_event_assistant.main import create_app
from vcenter_event_assistant.services.log_patterns.ledger import is_past_warmup
from vcenter_event_assistant.services.log_patterns.masking import MASK_VERSION
from vcenter_event_assistant.settings import Settings


@pytest.mark.asyncio
async def test_screenshot_e2e_seed_inserts_rows_and_api_exposes_guide(
    monkeypatch: pytest.MonkeyPatch,
    open_client,
) -> None:
    monkeypatch.setenv("SCREENSHOT_E2E_SEED", "1")
    await run_screenshot_e2e_seed_if_enabled()

    async with session_scope() as session:
        n_vc = (await session.execute(select(func.count()).select_from(VCenter))).scalar_one()
        n_g = (await session.execute(select(func.count()).select_from(EventTypeGuide))).scalar_one()
        n_ev = (await session.execute(select(func.count()).select_from(EventRecord))).scalar_one()
        n_m = (await session.execute(select(func.count()).select_from(MetricSample))).scalar_one()
        n_logs = (await session.execute(select(func.count()).select_from(LogRecord))).scalar_one()
        n_d = (await session.execute(select(func.count()).select_from(DigestRecord))).scalar_one()
        n_rules = (await session.execute(select(func.count()).select_from(AlertRule))).scalar_one()
        n_hist = (await session.execute(select(func.count()).select_from(AlertHistory))).scalar_one()
    assert n_vc == 1
    assert n_g == 3
    assert n_ev == 13
    assert n_m >= 1
    assert n_logs == 7
    assert n_d == 1
    assert n_rules == 1
    assert n_hist == 1

    app = create_app()
    async with open_client(app=app) as ac:
        resp = await ac.get("/api/events?limit=20")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    with_guide = [x for x in items if x.get("type_guide")]
    assert len(with_guide) >= 1
    assert with_guide[0]["type_guide"]["general_meaning"]


@pytest.mark.asyncio
async def test_screenshot_e2e_seed_skipped_without_env() -> None:
    await run_screenshot_e2e_seed_if_enabled()
    async with session_scope() as session:
        n_vc = (await session.execute(select(func.count()).select_from(VCenter))).scalar_one()
    assert n_vc == 0


@pytest.mark.asyncio
async def test_screenshot_e2e_seed_fills_timeline_with_all_four_kinds(
    monkeypatch: pytest.MonkeyPatch,
    open_client,
) -> None:
    """既定の期間（直近 1 時間）のタイムラインに、4 種類の出来事とメトリクスの超過区間が出る。"""
    monkeypatch.setenv("SCREENSHOT_E2E_SEED", "1")
    await run_screenshot_e2e_seed_if_enabled()

    # 起動から 5 分経って開いても、直近 1 時間にデモ行が残る。
    now = datetime.now(timezone.utc) + timedelta(minutes=5)
    period = {
        "from": (now - timedelta(hours=1)).isoformat(),
        "to": (now + timedelta(minutes=1)).isoformat(),
    }
    app = create_app()
    async with open_client(app=app) as ac:
        resp = await ac.post("/api/incident-timeline/view", json=period)
        logs_resp = await ac.get("/api/logs/patterns", params=period)
    assert logs_resp.status_code == 200
    groups = logs_resp.json()
    assert len(groups["items"]) >= 2
    assert groups["pending_count"] == 0
    assert resp.status_code == 200
    body = resp.json()
    highlights = body["highlights"]
    assert not highlights["log_patterns_backfill_pending"]
    first_warnings = highlights["new_log_patterns"]
    assert first_warnings
    [retry] = [item for item in first_warnings if item["max_severity_rank"] == 2]
    assert retry["count"] == 2
    [retry_group] = [item for item in groups["items"] if item["pattern_key"] == retry["pattern_key"]]
    assert retry_group["count"] == 3
    items = body["items"]
    kinds = {i["kind"] for i in items}
    assert kinds == {"event", "alert", "metric", "log"}
    assert body["omitted_sources"] == []
    [pattern] = body["highlights"]["detected_patterns"]
    assert (pattern["pattern_id"], pattern["entity_name"], pattern["event_count"]) == (
        "host-conn-flapping", "demo-esxi-01", 3,
    )

    metrics = [i for i in items if i["kind"] == "metric"]
    assert sorted(m["title"] for m in metrics) == [
        "CPU 使用率が閾値（80%）を超過",
        "メモリ使用率が閾値（85%）を超過",
    ]
    # 期間内で始まって終わる区間（期間の端で続いていない）
    for m in metrics:
        assert "継続" not in (m.get("detail") or "")

    events = [i for i in items if i["kind"] == "event"]
    assert all(e["entity_name"] for e in events)
    disconnects = [e for e in events if e["ref"]["event_type"] == "vim.event.HostConnectionLostEvent"]
    assert sum(e["count"] for e in disconnects) == 3
    assert {e["score"] for e in disconnects} == {40}
    changes = body["highlights"]["config_changes"]
    assert [(c["kind"], c["entity_name"], c["event_count"]) for c in changes] == [
        ("vm_reconfigure", "demo-vm-01", 2),
        ("maintenance_exit", "demo-esxi-01", 1),
        ("maintenance_enter", "demo-esxi-01", 1),
    ]
    assert changes[0]["user_names"] == ["demo-operator"]
    assert changes[0]["event_types"] == [
        "vim.event.VmReconfiguredEvent", "task.success.VirtualMachine.reconfigure"
    ]
    [incident] = [e for e in events if e["ref"]["event_type"] == "vim.event.ScreenshotDemoEventC"]
    assert changes[0]["last_utc"] < incident["timestamp_utc"]
    change_times = {e["timestamp_utc"] for e in events if e["config_change_kind"]}
    assert change_times.isdisjoint(
        e["timestamp_utc"] for e in events if not e["config_change_kind"]
    )
    async with session_scope() as session:
        rows = list(await session.scalars(
            select(EventRecord).where(EventRecord.id.in_(changes[0]["event_ids"]))
        ))
    assert {row.collector_id for row in rows} == {"builtin.vcenter.events", "builtin.vcenter.tasks"}
    assert rows[0].chain_id is not None and rows[0].chain_id == rows[1].chain_id
    # 同じ種別・同じ対象の連続は 1 行にまとまる
    assert [e["count"] for e in events].count(2) == 1
    logs = [i for i in items if i["kind"] == "log"]
    assert sorted(log["count"] for log in logs) == [1, 3]
    assert any(b["metric_breach"] > 0 for b in body["overview"])
    assert any(b["log_error"] > 0 for b in body["overview"])


@pytest.mark.asyncio
async def test_screenshot_e2e_seed_inventory_history(monkeypatch) -> None:
    from vcenter_event_assistant.db.models import (
        InventoryObject,
        InventoryRelation,
        InventorySyncRun,
        InventorySyncState,
    )
    from vcenter_event_assistant.mocks.mock_inventory import mock_inventory

    monkeypatch.setenv("SCREENSHOT_E2E_SEED", "1")
    await run_screenshot_e2e_seed_if_enabled()
    async with session_scope() as session:
        # この変更より前にシードした DB を再現する。
        for model in (
            InventorySyncState,
            InventorySyncRun,
            InventoryRelation,
            InventoryObject,
        ):
            await session.execute(delete(model))
    await run_screenshot_e2e_seed_if_enabled()
    await run_screenshot_e2e_seed_if_enabled()
    async with session_scope() as session:
        state = (await session.scalars(select(InventorySyncState))).one()
        vc = await session.get(VCenter, state.vcenter_id)
        current = mock_inventory(
            state.last_success_at.replace(tzinfo=timezone.utc), vcenter_name=vc.name
        )
        collected = set(await session.scalars(select(InventoryObject.moid)))
        event_targets = set(await session.scalars(select(EventRecord.entity_moid)))
        metric_targets = set(await session.scalars(select(MetricSample.entity_moid)))
        assert event_targets | metric_targets <= collected
        assert state.instance_uuid == current.instance_uuid
        rows = (await session.scalars(select(InventoryRelation))).all()
        closed = [r for r in rows if r.valid_to is not None]
        assert len(closed) == 1 and closed[0].kind == "vm_host"
        assert state.first_success_at == closed[0].valid_from
        assert state.first_success_at < await session.scalar(
            select(func.min(EventRecord.occurred_at))
        )
        assert closed[0].parent_moid == "host-9001"
        vm_host = next(
            row
            for row in rows
            if row.kind == "vm_host"
            and row.child_moid == "vm-9001"
            and row.valid_to is None
        )
        assert vm_host.parent_moid == "host-9002"
        assert closed[0].valid_to == vm_host.valid_from
        later = state.last_success_at.replace(tzinfo=timezone.utc) + timedelta(
            minutes=30
        )
        assert (
            mock_inventory(later, vcenter_name=vc.name).relations == current.relations
        )
        assert {
            (r.kind, r.child_moid, r.parent_moid) for r in rows if r.valid_to is None
        } == current.relations
        runs = (await session.scalars(select(InventorySyncRun.observed_at))).all()
        assert state.last_success_at in runs



async def test_screenshot_seed_log_patterns(monkeypatch) -> None:
    monkeypatch.setenv("SCREENSHOT_E2E_SEED", "1")
    await run_screenshot_e2e_seed_if_enabled()
    await run_screenshot_e2e_seed_if_enabled()
    async with session_scope() as session:
        state = await session.get(LogPatternBackfillState, MASK_VERSION)
        logs = (await session.scalars(select(LogRecord))).all()
        ledger = (await session.scalars(select(LogPattern))).all()
        assert state.last_id == state.upper_id == state.pending_upper_id == max(log.id for log in logs)
        assert sum(pattern.total_count for pattern in ledger) == len(logs)
        assert {log.pattern_key for log in logs} == {pattern.pattern_key for pattern in ledger}
        [new_warning] = [pattern for pattern in ledger if pattern.max_severity_rank == 2]
        assert new_warning.total_count == 3
        assert new_warning.first_seen_at < new_warning.warning_first_seen_at
        incident = await session.scalar(select(EventRecord).where(EventRecord.notable_score == 85))
        assert new_warning.warning_first_seen_at < incident.occurred_at
        baseline = await session.get(LogPatternBaseline, (
            new_warning.vcenter_id, new_warning.warning_first_source_id, new_warning.log_kind, MASK_VERSION,
        ))
        assert is_past_warmup(new_warning.warning_first_seen_at, baseline.started_at,
                              state.completed_at, Settings().log_pattern_warmup_days)
