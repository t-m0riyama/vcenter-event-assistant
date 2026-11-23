import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import AlertHistory, AlertRule, AlertState, MetricSample, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alerting.alert_eval import AlertEvaluator
from vcenter_event_assistant.settings import get_settings

@pytest.mark.asyncio
async def test_alerts_rules_crud(client: AsyncClient):
    # Create
    resp = await client.post("/api/alerts/rules", json={
        "name": "High CPU Test",
        "rule_type": "metric_threshold",
        "alert_level": "error",
        "config": {"metric_key": "host.cpu.usage_pct", "threshold": 90},
    })
    assert resp.status_code == 201
    rule_id = resp.json()["id"]
    revision = resp.json()["revision"]
    assert uuid.UUID(revision).version == 4
    assert resp.json()["alert_level"] == "error"
    
    # List
    resp = await client.get("/api/alerts/rules")
    assert resp.status_code == 200
    assert any(r["id"] == rule_id and r["revision"] == revision for r in resp.json())
    
    # Patch
    resp = await client.patch(f"/api/alerts/rules/{rule_id}", json={
        "revision": revision,
        "is_enabled": False,
        "alert_level": "critical",
    })
    assert resp.status_code == 200
    assert resp.json()["is_enabled"] is False
    assert resp.json()["alert_level"] == "critical"
    assert resp.json()["revision"] != revision
    
    # Delete
    resp = await client.delete(f"/api/alerts/rules/{rule_id}")
    assert resp.status_code == 204
    
    # Check deleted
    resp = await client.get("/api/alerts/rules")
    assert not any(r["id"] == rule_id for r in resp.json())

@pytest.mark.asyncio
async def test_alerts_rules_invalid_level(client: AsyncClient):
    resp = await client.post(
        "/api/alerts/rules",
        json={
            "name": "Bad Level",
            "rule_type": "event_score",
            "alert_level": "info",
            "config": {"threshold": 1},
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_alerts_rules_patch_name_success(client: AsyncClient):
    create_resp = await client.post(
        "/api/alerts/rules",
        json={
            "name": "Patch Name Before",
            "rule_type": "event_score",
            "alert_level": "warning",
            "config": {"threshold": 1},
        },
    )
    assert create_resp.status_code == 201
    rule_id = create_resp.json()["id"]

    patch_resp = await client.patch(
        f"/api/alerts/rules/{rule_id}",
        json={"revision": create_resp.json()["revision"], "name": "Patch Name After"},
    )
    assert patch_resp.status_code == 200
    body = patch_resp.json()
    assert body["id"] == rule_id
    assert body["name"] == "Patch Name After"


@pytest.mark.asyncio
async def test_alerts_rules_patch_name_conflict_returns_409(client: AsyncClient):
    first_resp = await client.post(
        "/api/alerts/rules",
        json={
            "name": "Patch Conflict A",
            "rule_type": "event_score",
            "alert_level": "warning",
            "config": {"threshold": 1},
        },
    )
    assert first_resp.status_code == 201
    first_id = first_resp.json()["id"]

    second_resp = await client.post(
        "/api/alerts/rules",
        json={
            "name": "Patch Conflict B",
            "rule_type": "metric_threshold",
            "alert_level": "error",
            "config": {"metric_key": "host.cpu.usage_pct", "threshold": 90},
        },
    )
    assert second_resp.status_code == 201
    second_id = second_resp.json()["id"]

    path = f"/api/alerts/rules/{second_id}"
    revision = second_resp.json()["revision"]
    patch_resp = await client.patch(path, json={"revision": revision, "name": "Patch Conflict A"})
    assert patch_resp.status_code == 409
    assert patch_resp.json()["detail"] == "Alert rule with this name already exists"
    assert "X-VEA-Error-Code" not in patch_resp.headers

    verify_resp = await client.get("/api/alerts/rules")
    assert verify_resp.status_code == 200
    by_id = {item["id"]: item for item in verify_resp.json()}
    assert by_id[first_id]["name"] == "Patch Conflict A"
    assert by_id[second_id]["name"] == "Patch Conflict B"
    assert by_id[second_id]["revision"] == revision

    updated = await client.patch(path, json={"revision": revision, "is_enabled": False})
    assert updated.status_code == 200
    stale = await client.patch(path, json={"revision": revision, "name": "Patch Conflict A"})
    assert stale.status_code == 409
    assert stale.headers["X-VEA-Error-Code"] == "alert_rule_stale"


@pytest.mark.asyncio
async def test_alerts_rules_patch_config_updates_config_only(client: AsyncClient):
    create_resp = await client.post(
        "/api/alerts/rules",
        json={
            "name": "Patch Config Rule",
            "rule_type": "metric_threshold",
            "alert_level": "critical",
            "config": {"metric_key": "host.cpu.usage_pct", "threshold": 90, "window_minutes": 5},
        },
    )
    assert create_resp.status_code == 201
    rule_id = create_resp.json()["id"]

    patch_resp = await client.patch(
        f"/api/alerts/rules/{rule_id}",
        json={
            "revision": create_resp.json()["revision"],
            "config": {"metric_key": "host.cpu.usage_pct", "threshold": 95},
        },
    )
    assert patch_resp.status_code == 200
    body = patch_resp.json()
    assert body["id"] == rule_id
    assert body["config"] == {"metric_key": "host.cpu.usage_pct", "threshold": 95}
    assert body["name"] == "Patch Config Rule"
    assert body["rule_type"] == "metric_threshold"
    assert body["alert_level"] == "critical"


@pytest.mark.asyncio
async def test_alert_rule_patch_requires_revision_and_rejects_reused_id(client: AsyncClient):
    payload = {"name": "Recreated rule", "rule_type": "event_score", "alert_level": "warning"}
    response = await client.post("/api/alerts/rules", json=payload)
    assert response.status_code == 201
    original = response.json()
    path = f"/api/alerts/rules/{original['id']}"
    change = {"alert_level": "error"}

    assert (await client.patch(path, json=change)).status_code == 422
    assert (await client.patch(path, json={**change, "revision": "invalid"})).status_code == 422
    assert (await client.delete(path)).status_code == 204

    stale_change = {**change, "revision": original["revision"]}
    assert (await client.patch(path, json=stale_change)).status_code == 404

    response = await client.post("/api/alerts/rules", json=payload)
    assert response.status_code == 201
    replacement = response.json()
    assert replacement["id"] == original["id"]  # SQLite reuses the deleted ID.
    assert replacement["revision"] != original["revision"]
    stale = await client.patch(path, json=stale_change)
    assert stale.status_code == 409
    assert stale.headers["X-VEA-Error-Code"] == "alert_rule_stale"
    assert (await client.get("/api/alerts/rules")).json() == [replacement]


async def test_concurrent_alert_rule_patch_keeps_winning_update_in_memory(open_client, monkeypatch):
    monkeypatch.setenv("VEA_AUTH_ENABLED", "0")
    get_settings.cache_clear()
    async with open_client(role=None) as client:
        created = await client.post("/api/alerts/rules", json={
            "name": "Concurrent rule", "rule_type": "event_score", "alert_level": "warning",
        })
        assert created.status_code == 201
        rule = created.json()
        path = f"/api/alerts/rules/{rule['id']}"

        writer_has_updated = asyncio.Event()
        other_has_connection = asyncio.Event()
        finish_first_commit = asyncio.Event()
        update_sessions = []
        connections = []
        scalars = AsyncSession.scalars
        commit = AsyncSession.commit

        async def track_rule_update(session, statement, *args, **kwargs):
            if statement.is_update and statement.table.name == "alert_rules":
                connection = await session.connection()
                connections.append(connection.sync_connection.connection.driver_connection)
                update_sessions.append(session)
                if len(connections) == 2:
                    other_has_connection.set()
            return await scalars(session, statement, *args, **kwargs)

        async def hold_first_commit(session):
            if update_sessions and session is update_sessions[0] and not writer_has_updated.is_set():
                writer_has_updated.set()
                await finish_first_commit.wait()
            await commit(session)

        monkeypatch.setattr(AsyncSession, "scalars", track_rule_update)
        monkeypatch.setattr(AsyncSession, "commit", hold_first_commit)

        async def save(threshold):
            return await client.patch(path, json={
                "revision": rule["revision"], "config": {"threshold": threshold},
            })

        async with asyncio.TaskGroup() as tasks:
            first = tasks.create_task(save(70))
            try:
                await asyncio.wait_for(writer_has_updated.wait(), timeout=5)
                second = tasks.create_task(save(90))
                await asyncio.wait_for(other_has_connection.wait(), timeout=5)
                assert connections[0] is not connections[1]
            finally:
                finish_first_commit.set()

        assert first.result().status_code == 200
        assert second.result().status_code == 409
        assert second.result().headers["X-VEA-Error-Code"] == "alert_rule_stale"
        saved = first.result().json()
        assert saved["config"] == {"threshold": 70}
        assert saved["revision"] != rule["revision"]
        assert (await client.get("/api/alerts/rules")).json() == [saved]


@pytest.mark.asyncio
async def test_alerts_history_includes_alert_level(client: AsyncClient):
    async with session_scope() as session:
        rule = AlertRule(
            name="History Level Rule",
            rule_type="event_score",
            alert_level="critical",
            config={"threshold": 1},
        )
        session.add(rule)
        await session.flush()
        session.add(
            AlertHistory(
                rule_id=rule.id,
                alert_level="critical",
                state="firing",
                context_key="ctx",
                notified_at=datetime.now(timezone.utc),
                channel="email",
                success=True,
            )
        )

    resp = await client.get("/api/alerts/history")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert any(i.get("alert_level") == "critical" for i in items)


@pytest.mark.asyncio
async def test_alerts_history_list(client: AsyncClient):
    # 履歴を1件手動で作成（または API 経由で評価を走らせる）
    # ここでは API のレスポンス形式を確認するため空の状態でも OK
    resp = await client.get("/api/alerts/history")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)


@pytest.mark.asyncio
async def test_alert_rules_import_duplicate_name_returns_400(client: AsyncClient):
    resp = await client.post(
        "/api/alerts/rules/import",
        json={
            "overwrite_existing": True,
            "delete_rules_not_in_import": False,
            "rules": [
                {
                    "name": "Dup Rule",
                    "rule_type": "event_score",
                    "alert_level": "warning",
                    "config": {"threshold": 1},
                },
                {
                    "name": "Dup Rule",
                    "rule_type": "metric_threshold",
                    "alert_level": "error",
                    "config": {"metric_key": "host.cpu.usage_pct", "threshold": 90},
                },
            ],
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "duplicate name in rules"


@pytest.mark.asyncio
async def test_alert_rules_import_overwrite_existing_updates_fields(client: AsyncClient):
    created = await client.post(
        "/api/alerts/rules",
        json={
            "name": "Overwrite Target",
            "rule_type": "event_score",
            "alert_level": "warning",
            "config": {"threshold": 1},
        },
    )
    assert created.status_code == 201

    original = created.json()
    imported = {
        "name": "Overwrite Target",
        "rule_type": "metric_threshold",
        "alert_level": "critical",
        "config": {"metric_key": "host.cpu.usage_pct", "threshold": 95, "window_minutes": 5},
    }
    path = "/api/alerts/rules/import"
    skipped = await client.post(path, json={"overwrite_existing": False, "rules": [imported]})
    assert skipped.status_code == 200
    assert (await client.get("/api/alerts/rules")).json() == [original]

    imp = await client.post(path, json={"overwrite_existing": True, "rules": [imported]})
    assert imp.status_code == 200
    assert imp.json()["rules_count"] == 1

    listed = await client.get("/api/alerts/rules")
    assert listed.status_code == 200
    by_name = {item["name"]: item for item in listed.json()}
    target = by_name["Overwrite Target"]
    assert target["id"] == original["id"]
    assert target["revision"] != original["revision"]
    assert target["rule_type"] == "metric_threshold"
    assert target["alert_level"] == "critical"
    assert target["config"] == {"metric_key": "host.cpu.usage_pct", "threshold": 95, "window_minutes": 5}

    path = f"/api/alerts/rules/{target['id']}"
    stale = await client.patch(path, json={"revision": original["revision"], "alert_level": "error"})
    assert stale.status_code == 409
    assert stale.headers["X-VEA-Error-Code"] == "alert_rule_stale"
    assert (await client.get("/api/alerts/rules")).json() == [target]


@pytest.mark.asyncio
async def test_alert_rules_import_delete_not_in_file_removes_orphans(client: AsyncClient):
    first = await client.post(
        "/api/alerts/rules",
        json={
            "name": "Orphan Rule",
            "rule_type": "event_score",
            "alert_level": "warning",
            "config": {"threshold": 1},
        },
    )
    assert first.status_code == 201
    second = await client.post(
        "/api/alerts/rules",
        json={
            "name": "Keep Rule",
            "rule_type": "event_score",
            "alert_level": "error",
            "config": {"threshold": 2},
        },
    )
    assert second.status_code == 201

    imp = await client.post(
        "/api/alerts/rules/import",
        json={
            "overwrite_existing": True,
            "delete_rules_not_in_import": True,
            "rules": [
                {
                    "name": "Keep Rule",
                    "rule_type": "metric_threshold",
                    "alert_level": "critical",
                    "config": {"metric_key": "host.cpu.usage_pct", "threshold": 99},
                },
            ],
        },
    )
    assert imp.status_code == 200
    assert imp.json()["rules_count"] == 1

    listed = await client.get("/api/alerts/rules")
    assert listed.status_code == 200
    names = [item["name"] for item in listed.json()]
    assert names == ["Keep Rule"]


@pytest.mark.asyncio
async def test_alert_rules_import_empty_delete_rejected(client: AsyncClient):
    first = await client.post(
        "/api/alerts/rules",
        json={
            "name": "Delete All A",
            "rule_type": "event_score",
            "alert_level": "warning",
            "config": {"threshold": 1},
        },
    )
    assert first.status_code == 201

    imp = await client.post(
        "/api/alerts/rules/import",
        json={
            "overwrite_existing": True,
            "delete_rules_not_in_import": True,
            "rules": [],
        },
    )
    assert imp.status_code == 422

    listed = await client.get("/api/alerts/rules")
    assert listed.status_code == 200
    assert any(r["name"] == "Delete All A" for r in listed.json())


@pytest.mark.asyncio
async def test_alerts_history_can_resolve_when_event_score_firing(client: AsyncClient):
    async with session_scope() as session:
        rule = AlertRule(
            name="Resolve UI Rule",
            rule_type="event_score",
            alert_level="warning",
            config={"threshold": 50},
        )
        session.add(rule)
        await session.flush()
        session.add(
            AlertState(
                rule_id=rule.id,
                state="firing",
                context_key="vim.event.ExampleEvent",
                fired_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            AlertHistory(
                rule_id=rule.id,
                alert_level="warning",
                state="firing",
                context_key="vim.event.ExampleEvent",
                notified_at=datetime.now(timezone.utc),
                channel="email",
                success=True,
            )
        )
        rule_id = rule.id

    resp = await client.get("/api/alerts/history")
    assert resp.status_code == 200
    item = next(i for i in resp.json()["items"] if i["rule_id"] == rule_id)
    assert item["rule_type"] == "event_score"
    assert item["can_resolve"] is True


@pytest.mark.asyncio
async def test_alerts_history_can_resolve_false_when_resolved(client: AsyncClient):
    async with session_scope() as session:
        rule = AlertRule(
            name="Resolved Rule",
            rule_type="event_score",
            alert_level="warning",
            config={"threshold": 50},
        )
        session.add(rule)
        await session.flush()
        session.add(
            AlertState(
                rule_id=rule.id,
                state="resolved",
                context_key="vim.event.ResolvedEvent",
                fired_at=datetime.now(timezone.utc),
                resolved_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            AlertHistory(
                rule_id=rule.id,
                alert_level="warning",
                state="firing",
                context_key="vim.event.ResolvedEvent",
                notified_at=datetime.now(timezone.utc),
                channel="email",
                success=True,
            )
        )
        rule_id = rule.id

    resp = await client.get("/api/alerts/history")
    item = next(i for i in resp.json()["items"] if i["rule_id"] == rule_id)
    assert item["can_resolve"] is False


@pytest.mark.asyncio
async def test_resolve_event_score_alert(client: AsyncClient):
    async with session_scope() as session:
        rule = AlertRule(
            name="Manual Resolve Rule",
            rule_type="event_score",
            alert_level="error",
            config={"threshold": 60},
        )
        session.add(rule)
        await session.flush()
        session.add(
            AlertState(
                rule_id=rule.id,
                state="firing",
                context_key="vim.event.ManualEvent",
                fired_at=datetime.now(timezone.utc),
            )
        )
        rule_id = rule.id
        context_key = "vim.event.ManualEvent"

    with patch.object(AlertEvaluator, "_enqueue_notification", new_callable=AsyncMock):
        resp = await client.post(
            "/api/alerts/states/resolve",
            json={"rule_id": rule_id, "context_key": context_key},
        )
    assert resp.status_code == 204

    async with session_scope() as session:
        res = await session.execute(
            select(AlertState).where(
                AlertState.rule_id == rule_id,
                AlertState.context_key == context_key,
            )
        )
        state = res.scalar_one()
        assert state.state == "resolved"
        assert state.resolved_at is not None


@pytest.mark.asyncio
async def test_resolve_event_score_alert_rejects_metric_rule(client: AsyncClient):
    async with session_scope() as session:
        rule = AlertRule(
            name="Metric Rule",
            rule_type="metric_threshold",
            alert_level="warning",
            config={"threshold": 90, "metric_key": "host.cpu.usage_pct"},
        )
        session.add(rule)
        await session.flush()
        session.add(
            AlertState(
                rule_id=rule.id,
                state="firing",
                context_key="host-1",
                fired_at=datetime.now(timezone.utc),
            )
        )
        rule_id = rule.id

    resp = await client.post(
        "/api/alerts/states/resolve",
        json={"rule_id": rule_id, "context_key": "host-1"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_resolve_event_score_alert_not_found(client: AsyncClient):
    resp = await client.post(
        "/api/alerts/states/resolve",
        json={"rule_id": 999999, "context_key": "missing"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_alert_history_row(client: AsyncClient):
    async with session_scope() as session:
        rule = AlertRule(
            name="Delete History Rule",
            rule_type="event_score",
            alert_level="warning",
            config={"threshold": 1},
        )
        session.add(rule)
        await session.flush()
        history = AlertHistory(
            rule_id=rule.id,
            alert_level="warning",
            state="firing",
            context_key="ctx-delete",
            notified_at=datetime.now(timezone.utc),
            channel="email",
            success=True,
        )
        session.add(history)
        await session.flush()
        history_id = history.id

    resp = await client.delete(f"/api/alerts/history/{history_id}")
    assert resp.status_code == 204

    async with session_scope() as session:
        assert await session.get(AlertHistory, history_id) is None


@pytest.mark.asyncio
async def test_delete_alert_history_not_found(client: AsyncClient):
    resp = await client.delete("/api/alerts/history/999999")
    assert resp.status_code == 404


_T0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)


async def _history_vcenter(name: str) -> uuid.UUID:
    vid = uuid.uuid4()
    async with session_scope() as session:
        session.add(VCenter(id=vid, name=name, host="h", port=443, username="u", password="p"))
    return vid


async def _history_sample(vid: uuid.UUID, moid: str, name: str, at: datetime) -> None:
    async with session_scope() as session:
        session.add(
            MetricSample(
                vcenter_id=vid, sampled_at=at, entity_type="HostSystem", entity_moid=moid,
                entity_name=name, metric_key="host.cpu.usage_pct", value=90.0,
            )
        )


async def _history_row(
    rule_type: str, context_key: str, *, occurred_at: datetime, notified_at: datetime | None = None, name: str
) -> int:
    async with session_scope() as session:
        rule = AlertRule(
            name=name, rule_type=rule_type, alert_level="critical",
            config={"metric_key": "host.cpu.usage_pct"} if rule_type == "metric_threshold" else {"threshold": 1},
        )
        session.add(rule)
        await session.flush()
        row = AlertHistory(
            rule_id=rule.id, alert_level="critical", state="firing", context_key=context_key,
            occurred_at=occurred_at, notified_at=notified_at or occurred_at, channel="none", success=None,
        )
        session.add(row)
        await session.flush()
        return row.id


async def _history_by_id(client: AsyncClient) -> dict[int, dict]:
    resp = await client.get("/api/alerts/history", params={"limit": 200})
    assert resp.status_code == 200
    return {i["id"]: i for i in resp.json()["items"]}


@pytest.mark.asyncio
async def test_alerts_history_resolves_vcenter_and_entity_for_metric_rows(client: AsyncClient):
    vid = await _history_vcenter("vc-hist-1")
    await _history_sample(vid, "host-1", "esx01", _T0)
    row_id = await _history_row("metric_threshold", f"{vid}:host-1", occurred_at=_T0 + timedelta(minutes=1), name="hist-cpu")
    item = (await _history_by_id(client))[row_id]
    assert item["vcenter_id"] == str(vid)
    assert item["entity_name"] == "esx01"
    assert item["entity_moid"] == "host-1"
    assert datetime.fromisoformat(item["occurred_at"].replace("Z", "+00:00")).replace(tzinfo=timezone.utc) == _T0 + timedelta(minutes=1)


@pytest.mark.asyncio
async def test_alerts_history_event_score_and_legacy_key_have_no_vcenter_or_entity(client: AsyncClient):
    vid = await _history_vcenter("vc-hist-2")
    await _history_sample(vid, "host-legacy", "esx-legacy", _T0)
    es = await _history_row("event_score", f"{vid}:host-legacy", occurred_at=_T0, name="hist-es")
    legacy = await _history_row("metric_threshold", "host-legacy", occurred_at=_T0, name="hist-legacy")
    items = await _history_by_id(client)
    for row_id in (es, legacy):
        assert items[row_id]["vcenter_id"] is None
        assert items[row_id]["entity_name"] is None
        assert items[row_id]["entity_moid"] is None
        assert items[row_id]["occurred_at"]


@pytest.mark.asyncio
async def test_alerts_history_same_moid_on_another_vcenter_is_not_mixed(client: AsyncClient):
    v1 = await _history_vcenter("vc-hist-3a")
    v2 = await _history_vcenter("vc-hist-3b")
    await _history_sample(v1, "host-1", "esx-on-vc1", _T0)
    await _history_sample(v2, "host-1", "esx-on-vc2", _T0 + timedelta(minutes=2))
    r1 = await _history_row("metric_threshold", f"{v1}:host-1", occurred_at=_T0 + timedelta(minutes=3), name="hist-mix-1")
    r2 = await _history_row("metric_threshold", f"{v2}:host-1", occurred_at=_T0 + timedelta(minutes=3), name="hist-mix-2")
    items = await _history_by_id(client)
    assert (items[r1]["vcenter_id"], items[r1]["entity_name"]) == (str(v1), "esx-on-vc1")
    assert (items[r2]["vcenter_id"], items[r2]["entity_name"]) == (str(v2), "esx-on-vc2")


@pytest.mark.asyncio
async def test_alerts_history_unresolvable_entity_keeps_vcenter_and_null_name(client: AsyncClient):
    vid = await _history_vcenter("vc-hist-4")
    row_id = await _history_row("metric_threshold", f"{vid}:host-none", occurred_at=_T0, name="hist-noname")
    item = (await _history_by_id(client))[row_id]
    assert item["vcenter_id"] == str(vid)
    assert item["entity_name"] is None


@pytest.mark.asyncio
async def test_alerts_history_occurred_at_stays_when_notified_at_advances(client: AsyncClient):
    row_id = await _history_row("event_score", "ctx-resend", occurred_at=_T0, name="hist-resend")
    before = (await _history_by_id(client))[row_id]
    async with session_scope() as session:
        row = await session.get(AlertHistory, row_id)
        assert row is not None
        row.notified_at = _T0 + timedelta(hours=2)
    after = (await _history_by_id(client))[row_id]
    assert after["occurred_at"] == before["occurred_at"]
    assert after["notified_at"] != before["notified_at"]


@pytest.mark.asyncio
async def test_event_pattern_rule_create_patch_and_import(client: AsyncClient):
    rule = {
        "name": "APD",
        "rule_type": "event_pattern",
        "alert_level": "error",
        "config": {"pattern_ids": ["apd-timeout"], "cooldown_minutes": 10},
    }
    invalid_config = {"pattern_ids": ["unknown"], "cooldown_minutes": 10}
    invalid_rule = {**rule, "config": invalid_config}
    assert (await client.post("/api/alerts/rules", json=invalid_rule)).status_code == 422
    created = await client.post("/api/alerts/rules", json=rule)
    assert created.status_code == 201
    stored = created.json()
    path = f"/api/alerts/rules/{stored['id']}"
    assert (await client.patch(path, json={
        "revision": stored["revision"], "config": invalid_config,
    })).status_code == 422
    updated = await client.patch(path, json={
        "revision": stored["revision"], "config": {"pattern_ids": [], "cooldown_minutes": 5},
    })
    assert updated.status_code == 200
    assert updated.json()["config"] == {"pattern_ids": [], "cooldown_minutes": 5}
    assert (await client.post("/api/alerts/rules/import", json={"rules": [invalid_rule]})).status_code == 422
    assert (await client.post("/api/alerts/rules/import", json={"rules": [rule]})).status_code == 200
    listed = await client.get("/api/alerts/rules")
    assert listed.json()[0]["config"] == rule["config"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule_type", "config", "status"), [
    ("metric_threshold", {"metric_key": "x", "threshold": 150}, 200),
    ("event_score", {"threshold": 150}, 422),
    ("event_score", {"cooldown_minutes": 0}, 422),
])
async def test_alert_rule_patch_config_validation_by_type(client, rule_type, config, status):
    create = await client.post("/api/alerts/rules", json={
        "name": "Validation",
        "rule_type": rule_type,
        "alert_level": "warning",
        "config": {"metric_key": "x", "threshold": 80},
    })
    assert create.status_code == 201
    rule = create.json()
    result = await client.patch(f"/api/alerts/rules/{rule['id']}", json={
        "revision": rule["revision"], "config": config,
    })
    assert result.status_code == status
    if status == 200:
        assert result.json()["config"] == config
    else:
        assert (await client.get("/api/alerts/rules")).json() == [rule]


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["threshold", "cooldown_minutes"])
@pytest.mark.parametrize("value", ["Infinity", "-Infinity", "NaN"])
async def test_event_score_rejects_nonfinite_config_on_create_patch_and_import(client, field, value):
    rule_json = (
        '{"name":"Score","rule_type":"event_score","alert_level":"warning",'
        f'"config":{{"{field}":{value}}}}}'
    )
    headers = {"Content-Type": "application/json"}
    result = await client.post("/api/alerts/rules", headers=headers, content=rule_json)
    assert result.status_code == 422
    result = await client.post(
        "/api/alerts/rules/import", headers=headers, content='{"rules":[' + rule_json + ']}',
    )
    assert result.status_code == 422
    created = await client.post("/api/alerts/rules", json={
        "name": "Score", "rule_type": "event_score", "alert_level": "warning",
    })
    assert created.status_code == 201
    rule = created.json()
    result = await client.patch(
        f"/api/alerts/rules/{rule['id']}", headers=headers,
        content=f'{{"revision":"{rule["revision"]}","config":{{"{field}":{value}}}}}',
    )
    assert result.status_code == 422
    assert (await client.get("/api/alerts/rules")).json() == [rule]


@pytest.mark.asyncio
async def test_event_pattern_normalizes_duplicate_ids_before_create_patch_and_import(client):
    entry = {"name": "Pattern", "rule_type": "event_pattern", "alert_level": "warning"}
    ids = ["ha-failover", "apd-timeout"]
    config = {"pattern_ids": [ids[0], ids[1], ids[0], ids[1]], "cooldown_minutes": 5}
    created = await client.post("/api/alerts/rules", json={**entry, "config": config})
    assert created.status_code == 201
    rule = created.json()
    assert rule["config"] == {**config, "pattern_ids": ids}

    patched = await client.patch(f"/api/alerts/rules/{rule['id']}", json={
        "revision": rule["revision"], "config": {**config, "pattern_ids": config["pattern_ids"][::-1]},
    })
    assert patched.status_code == 200
    assert patched.json()["config"] == {**config, "pattern_ids": ids[::-1]}

    imported = await client.post("/api/alerts/rules/import", json={
        "rules": [{**entry, "config": config}],
    })
    assert imported.status_code == 200
    [stored] = (await client.get("/api/alerts/rules")).json()
    assert stored["config"] == {**config, "pattern_ids": ids}
