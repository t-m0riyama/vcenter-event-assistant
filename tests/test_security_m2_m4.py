"""M-2 / M-3 / M-4 security API guards."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_alert_history_rejects_oversized_limit(client: AsyncClient) -> None:
    r = await client.get("/api/alerts/history", params={"limit": 5000})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_alert_rules_import_rejects_empty_delete(client: AsyncClient) -> None:
    r = await client.post(
        "/api/alerts/rules/import",
        json={"rules": [], "delete_rules_not_in_import": True},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_chat_rejects_excessive_time_range(client: AsyncClient) -> None:
    r = await client.post(
        "/api/chat/preview",
        json={
            "from": "2020-01-01T00:00:00Z",
            "to": "2026-01-01T00:00:00Z",
            "messages": [{"role": "user", "content": "test"}],
        },
    )
    assert r.status_code == 422
    detail = str(r.json().get("detail", ""))
    assert "90" in detail


@pytest.mark.asyncio
async def test_manual_snapshot_rejects_excessive_build_request_range(client: AsyncClient) -> None:
    """IncidentTimelineBuildRequest の期間の上限（90 日）を、スナップショットの保存の build_request_payload で確かめる。

    外側の from/to は短く正しい期間にし、422 が入れ子の条件から出ることを確かめる。
    """
    r = await client.post(
        "/api/incident-timeline/snapshots/manual",
        json={
            "from": "2026-01-01T00:00:00Z",
            "to": "2026-01-02T00:00:00Z",
            "timestamp_utc": "2026-01-01T12:00:00Z",
            "operator_note": "期間の上限の確認",
            "build_request_payload": {
                "from": "2020-01-01T00:00:00Z",
                "to": "2026-01-01T00:00:00Z",
            },
        },
    )
    assert r.status_code == 422
    assert all("build_request_payload" in error["loc"] for error in r.json()["detail"])
    detail = str(r.json().get("detail", ""))
    assert "90" in detail
