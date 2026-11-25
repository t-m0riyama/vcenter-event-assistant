"""``SCREENSHOT_E2E_SEED`` 時のドキュメント用 DB シード。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import asyncssh
import pytest
from sqlalchemy import delete, func, select, update

from vcenter_event_assistant.db.models import (
    AlertHistory,
    AlertRule,
    DiagnosticTarget,
    DigestRecord,
    EventRecord,
    EventTypeGuide,
    LogPattern,
    LogPatternBackfillState,
    LogPatternBaseline,
    LogRecord,
    MetricSample,
    SSHConnection,
    VCenter,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.dev.screenshot_e2e_seed import run_screenshot_e2e_seed_if_enabled
from vcenter_event_assistant.main import create_app
from vcenter_event_assistant.services.log_patterns.ledger import is_past_warmup
from vcenter_event_assistant.services.log_patterns.masking import MASK_VERSION
from vcenter_event_assistant.settings import Settings, get_settings
from vcenter_event_assistant.settings_binding import bind_settings


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
        unresolved = await ac.get("/api/incidents")
        resolved = await ac.get("/api/incidents?status=resolved")
        assert unresolved.status_code == resolved.status_code == 200
        [unresolved_row] = unresolved.json()["items"]
        [resolved_row] = resolved.json()["items"]
        assert unresolved.json()["total"] == resolved.json()["total"] == 1
        assert unresolved_row["status"] == "monitoring"
        assert resolved_row["status"] == "resolved"
        for row in (unresolved_row, resolved_row):
            response = await ac.get(f"/api/incidents/{row['id']}")
            assert response.status_code == 200
            detail = response.json()
            assert detail["events"]
            assert any(entry["kind"] == "note" for entry in detail["entries"])
            [link] = [entry for entry in detail["entries"] if entry["kind"] == "link"]
            assert f"イベント {len(detail['events'])} 件を追加しました。" in link["body"]
            if row["status"] == "monitoring":
                [change] = [entry for entry in detail["entries"] if entry["kind"] == "change"]
                assert change["body"] == "状態を「対応中」から「様子見」に変えました。"
                assert detail["alerts"] and "通知 1 件を追加しました。" in link["body"]
                [snapshot] = detail["snapshots"]
                assert snapshot["has_result"]
                assert "スナップショット 1 件を追加しました。" in link["body"]
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


async def test_screenshot_diagnostic_demo_uses_mock_target_and_saved_outputs(monkeypatch, open_client) -> None:
    monkeypatch.setenv("SCREENSHOT_E2E_SEED", "1")
    await run_screenshot_e2e_seed_if_enabled()

    # 診断を有効にしても、モックモードでなければ撮影用の接続先を入れない。
    monkeypatch.setenv("VEA_DIAGNOSTICS_ENABLED", "true")
    monkeypatch.setenv("VEA_SECRET_KEY", "screenshot-test")
    monkeypatch.setenv("MOCK_MODE", "0")
    get_settings.cache_clear()
    bind_settings(get_settings())
    await run_screenshot_e2e_seed_if_enabled()
    async with open_client() as client:
        assert (await client.get("/api/diagnostics/targets")).json() == []

    # 撮影用 DB が既にある場合にも、診断の例を一度だけ追加する。
    monkeypatch.setenv("MOCK_MODE", "1")
    get_settings.cache_clear()
    bind_settings(get_settings())
    await run_screenshot_e2e_seed_if_enabled()
    await run_screenshot_e2e_seed_if_enabled()

    async with open_client(username="demo-admin") as client, open_client("viewer") as viewer:
        incidents = (await viewer.get("/api/incidents", params={"q": "デモ: 診断コマンド"})).json()
        [incident] = incidents["items"]
        path = f"/api/incidents/{incident['id']}"
        [candidate] = (await viewer.get(f"{path}/procedures")).json()
        assert candidate["procedure"]["pattern_id"] == "nic-link-flapping"
        assert candidate["reasons"][0]["kind"] == "event"

        [target] = (await client.get("/api/diagnostics/targets")).json()
        assert target["host_moid"] == "mock-esxi"
        assert candidate["target"] == {"id": target["id"], "host_name": "mock-esxi.local"}
        hosts = await client.get(f"/api/diagnostics/vcenters/{target['vcenter_id']}/hosts")
        assert target["host_moid"] in {host["id"] for host in hosts.json()}

        detail = (await viewer.get(path)).json()
        assert [entry["kind"] for entry in detail["entries"]].count("diagnostic") == 2
        runs = detail["diagnostic_runs"]
        assert {(run["status"], run["exit_status"]) for run in runs} == {("succeeded", 0), ("failed", 1)}
        [truncated] = [run for run in runs if run["stdout_truncated"]]
        assert "stdout" not in truncated
        output = (await viewer.get(f"{path}/diagnostic-runs/{truncated['id']}")).json()
        assert len(output["stdout"].encode("utf-8")) == 65_536
        assert output["stdout_truncated"] and output["executed"] is True
        assert {entry["body"] for entry in detail["entries"] if entry["kind"] == "diagnostic"} == {
            "診断「ホスト名」を mock-esxi.local で実行した（終了コード 0）",
            "診断「NIC の統計」を mock-esxi.local で実行した（終了コード 1）",
        }

        run_path = f"/api/diagnostics/incidents/{incident['id']}/runs"
        payload = {"target_id": target["id"], "params": {"vmnic": "vmnic0"}, "command": {"builtin": "esxi.nic-stats"}}
        response = await client.post(f"{run_path}/preview", json=payload)
        assert response.status_code == 200, response.text
        preview = response.json()
        assert preview["ssh_host"] == "mock-esxi.local"
        assert preview["ssh_username"] == "demo-diagnostics"
        assert len(preview["fingerprint"]) == 64

        response = await client.post(run_path, json={**payload, "fingerprint": preview["fingerprint"]})
        assert response.status_code == 200, response.text
        run = response.json()
        assert run["status"] == "succeeded"
        assert run["executed"] is False
        assert run["command_line"] == preview["command_line"]


@pytest.mark.parametrize("existing", [
    "対象の手動登録", "インシデント削除", "対象も削除", "接続先も削除", "対象だけ削除", "未承認の接続先",
])
async def test_screenshot_diagnostics_seed_reuses_existing_rows(monkeypatch, open_client, existing):
    monkeypatch.setenv("SCREENSHOT_E2E_SEED", "1")
    monkeypatch.setenv("MOCK_MODE", "1")
    monkeypatch.setenv("VEA_DIAGNOSTICS_ENABLED", "false")
    monkeypatch.setenv("VEA_SECRET_KEY", "screenshot-test")
    get_settings.cache_clear()
    bind_settings(get_settings())
    await run_screenshot_e2e_seed_if_enabled()
    monkeypatch.setenv("VEA_DIAGNOSTICS_ENABLED", "true")
    get_settings.cache_clear()
    bind_settings(get_settings())
    base = "/api/diagnostics"

    async with open_client() as client:
        if existing == "対象の手動登録":
            [vc] = (await client.get("/api/vcenters")).json()
            key = asyncssh.generate_private_key("ssh-ed25519").export_private_key("openssh").decode()
            credential = (await client.post(f"{base}/ssh/credentials", json={
                "name": "デモ手動登録の鍵", "private_key": key,
            })).json()
            connection = (await client.post(f"{base}/ssh/connections", json={
                "name": "デモ手動登録の接続先", "host": "manual.demo.invalid", "username": "demo-manual",
                "credential_id": credential["id"],
            })).json()
            response = await client.post(f"{base}/targets", json={
                "vcenter_id": vc["id"], "product": "esxi", "host_moid": "mock-esxi",
                "host_name": "デモ手動登録の対象", "ssh_connection_id": connection["id"],
            })
            assert response.status_code in (200, 201), response.text
            target = response.json()
        else:
            await run_screenshot_e2e_seed_if_enabled()
            [target] = (await client.get(f"{base}/targets")).json()
            [connection] = (await client.get(f"{base}/ssh/connections")).json()
            [credential] = (await client.get(f"{base}/ssh/credentials")).json()
            [incident] = (await client.get("/api/incidents", params={"q": "デモ: 診断コマンド"})).json()["items"]
            if existing != "対象だけ削除":
                assert (await client.delete(f"/api/incidents/{incident['id']}")).status_code == 204
            async with session_scope() as session:
                if existing in {"対象も削除", "接続先も削除", "対象だけ削除", "未承認の接続先"}:
                    await session.execute(delete(DiagnosticTarget))
                if existing == "接続先も削除":
                    await session.execute(delete(SSHConnection))
                if existing == "未承認の接続先":
                    await session.execute(update(SSHConnection).values(approved_key=None))
                if existing == "インシデント削除":
                    await session.execute(update(EventRecord).where(
                        EventRecord.vmware_key == 9_004_001,
                    ).values(occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
            if existing == "未承認の接続先":
                [connection] = (await client.get(f"{base}/ssh/connections")).json()

        await run_screenshot_e2e_seed_if_enabled()
        await run_screenshot_e2e_seed_if_enabled()
        [seeded_target] = (await client.get(f"{base}/targets")).json()
        [seeded_connection] = (await client.get(f"{base}/ssh/connections")).json()
        [seeded_credential] = (await client.get(f"{base}/ssh/credentials")).json()
        assert seeded_credential["id"] == credential["id"]
        if existing != "接続先も削除":
            assert seeded_connection == connection
        if existing in {"対象の手動登録", "インシデント削除"}:
            assert seeded_target == target

        [seeded_incident] = (await client.get("/api/incidents", params={"q": "デモ: 診断コマンド"})).json()["items"]
        detail = (await client.get(f"/api/incidents/{seeded_incident['id']}")).json()
        assert len(detail["diagnostic_runs"]) == 2
        assert {run["ssh_host"] for run in detail["diagnostic_runs"]} == {"mock-esxi.local"}
        if existing == "対象だけ削除":
            assert seeded_incident["id"] == incident["id"]
            [candidate] = (await client.get(f"/api/incidents/{incident['id']}/procedures")).json()
            assert candidate["target"]["id"] == seeded_target["id"]
        if existing == "インシデント削除":
            [event] = detail["events"]
            assert detail["started_at"] == event["occurred_at"]
        if existing == "未承認の接続先":
            preview = await client.post(f"/api/diagnostics/incidents/{seeded_incident['id']}/runs/preview", json={
                "target_id": seeded_target["id"], "params": {}, "command": {"builtin": "esxi.hostname"},
            })
            assert preview.status_code == 409
            assert preview.headers["X-VEA-Error-Code"] == "diagnostic_host_key_unapproved"
