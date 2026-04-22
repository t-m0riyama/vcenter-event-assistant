import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_alerts_rules_crud(client: AsyncClient):
    # Create
    resp = await client.post("/api/alerts/rules", json={
        "name": "High CPU Test",
        "rule_type": "metric_threshold",
        "config": {"threshold": 90}
    })
    assert resp.status_code == 201
    rule_id = resp.json()["id"]
    
    # List
    resp = await client.get("/api/alerts/rules")
    assert resp.status_code == 200
    assert any(r["id"] == rule_id for r in resp.json())
    
    # Patch
    resp = await client.patch(f"/api/alerts/rules/{rule_id}", json={
        "is_enabled": False
    })
    assert resp.status_code == 200
    assert resp.json()["is_enabled"] is False
    
    # Delete
    resp = await client.delete(f"/api/alerts/rules/{rule_id}")
    assert resp.status_code == 204
    
    # Check deleted
    resp = await client.get("/api/alerts/rules")
    assert not any(r["id"] == rule_id for r in resp.json())

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
