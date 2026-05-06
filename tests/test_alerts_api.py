from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from vcenter_event_assistant.db.models import AlertHistory, AlertRule
from vcenter_event_assistant.db.session import session_scope

@pytest.mark.asyncio
async def test_alerts_rules_crud(client: AsyncClient):
    # Create
    resp = await client.post("/api/alerts/rules", json={
        "name": "High CPU Test",
        "rule_type": "metric_threshold",
        "alert_level": "error",
        "config": {"threshold": 90},
    })
    assert resp.status_code == 201
    rule_id = resp.json()["id"]
    assert resp.json()["alert_level"] == "error"
    
    # List
    resp = await client.get("/api/alerts/rules")
    assert resp.status_code == 200
    assert any(r["id"] == rule_id for r in resp.json())
    
    # Patch
    resp = await client.patch(f"/api/alerts/rules/{rule_id}", json={
        "is_enabled": False,
        "alert_level": "critical",
    })
    assert resp.status_code == 200
    assert resp.json()["is_enabled"] is False
    assert resp.json()["alert_level"] == "critical"
    
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
        json={"name": "Patch Name After"},
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
            "config": {"threshold": 90},
        },
    )
    assert second_resp.status_code == 201
    second_id = second_resp.json()["id"]

    patch_resp = await client.patch(
        f"/api/alerts/rules/{second_id}",
        json={"name": "Patch Conflict A"},
    )
    assert patch_resp.status_code == 409
    assert patch_resp.json()["detail"] == "Alert rule with this name already exists"

    verify_resp = await client.get("/api/alerts/rules")
    assert verify_resp.status_code == 200
    by_id = {item["id"]: item for item in verify_resp.json()}
    assert by_id[first_id]["name"] == "Patch Conflict A"
    assert by_id[second_id]["name"] == "Patch Conflict B"


@pytest.mark.asyncio
async def test_alerts_rules_patch_config_updates_config_only(client: AsyncClient):
    create_resp = await client.post(
        "/api/alerts/rules",
        json={
            "name": "Patch Config Rule",
            "rule_type": "metric_threshold",
            "alert_level": "critical",
            "config": {"threshold": 90, "window_minutes": 5},
        },
    )
    assert create_resp.status_code == 201
    rule_id = create_resp.json()["id"]

    patch_resp = await client.patch(
        f"/api/alerts/rules/{rule_id}",
        json={"config": {"threshold": 95}},
    )
    assert patch_resp.status_code == 200
    body = patch_resp.json()
    assert body["id"] == rule_id
    assert body["config"] == {"threshold": 95}
    assert body["name"] == "Patch Config Rule"
    assert body["rule_type"] == "metric_threshold"
    assert body["alert_level"] == "critical"


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
                    "config": {"threshold": 90},
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

    imp = await client.post(
        "/api/alerts/rules/import",
        json={
            "overwrite_existing": True,
            "delete_rules_not_in_import": False,
            "rules": [
                {
                    "name": "Overwrite Target",
                    "rule_type": "metric_threshold",
                    "alert_level": "critical",
                    "config": {"threshold": 95, "window_minutes": 5},
                },
            ],
        },
    )
    assert imp.status_code == 200
    assert imp.json()["rules_count"] == 1

    listed = await client.get("/api/alerts/rules")
    assert listed.status_code == 200
    by_name = {item["name"]: item for item in listed.json()}
    target = by_name["Overwrite Target"]
    assert target["rule_type"] == "metric_threshold"
    assert target["alert_level"] == "critical"
    assert target["config"] == {"threshold": 95, "window_minutes": 5}


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
                    "config": {"threshold": 99},
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
async def test_alert_rules_import_delete_all_when_empty_rules(client: AsyncClient):
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
    second = await client.post(
        "/api/alerts/rules",
        json={
            "name": "Delete All B",
            "rule_type": "metric_threshold",
            "alert_level": "error",
            "config": {"threshold": 90},
        },
    )
    assert second.status_code == 201

    imp = await client.post(
        "/api/alerts/rules/import",
        json={
            "overwrite_existing": True,
            "delete_rules_not_in_import": True,
            "rules": [],
        },
    )
    assert imp.status_code == 200
    assert imp.json()["rules_count"] == 0

    listed = await client.get("/api/alerts/rules")
    assert listed.status_code == 200
    assert listed.json() == []
