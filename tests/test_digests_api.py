"""GET/POST /api/digests のテスト。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from vcenter_event_assistant.db.models import EventRecord
from vcenter_event_assistant.db.session import session_scope


@pytest.mark.asyncio
async def test_list_digests_empty_then_run(client: AsyncClient) -> None:
    r = await client.get("/api/digests")
    assert r.status_code == 200
    data = r.json()
    assert data["items"] == []
    assert data["total"] == 0

    r = await client.post("/api/digests/run", json={})
    assert r.status_code == 200
    row = r.json()
    assert row["id"] >= 1
    assert row["kind"] == "daily"
    assert row["status"] == "ok"
    assert "body_markdown" in row

    r2 = await client.get("/api/digests")
    assert r2.status_code == 200
    assert r2.json()["total"] == 1


@pytest.mark.asyncio
async def test_get_digest_by_id(client: AsyncClient) -> None:
    await client.post("/api/digests/run", json={})
    r = await client.get("/api/digests")
    did = r.json()["items"][0]["id"]
    g = await client.get(f"/api/digests/{did}")
    assert g.status_code == 200
    assert g.json()["id"] == did


@pytest.mark.asyncio
async def test_run_digest_with_explicit_window(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "digest-vc",
            "host": "h",
            "port": 443,
            "username": "u",
            "password": "p",
            "is_enabled": True,
        },
    )
    assert r.status_code == 201
    vid = uuid.UUID(r.json()["id"])
    t0 = datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc)
    async with session_scope() as session:
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=t0,
                event_type="VmPoweredOnEvent",
                message="m",
                severity="info",
                vmware_key=99,
                notable_score=1,
            )
        )

    fr = "2026-03-10T00:00:00Z"
    to = "2026-03-11T00:00:00Z"
    r = await client.post(
        "/api/digests/run",
        json={"kind": "daily", "from_time": fr, "to_time": to},
    )
    assert r.status_code == 200
    assert "VmPoweredOnEvent" in r.json()["body_markdown"]
