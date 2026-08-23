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
