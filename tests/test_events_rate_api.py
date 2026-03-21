"""GET /api/events/rate-series and /api/events/event-types."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest
from httpx import AsyncClient

from vcenter_event_assistant.db.models import EventRecord
from vcenter_event_assistant.db.session import session_scope


@pytest.mark.asyncio
async def test_rate_series_buckets_counts_and_zeros(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "rate-vc",
            "host": "vc.example",
            "port": 443,
            "username": "u",
            "password": "p",
            "is_enabled": True,
        },
    )
    assert r.status_code == 201
    vid = uuid.UUID(r.json()["id"])

    b = 300
    t0 = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    t_same = t0 + timedelta(seconds=100)
    t_next = t0 + timedelta(seconds=400)

    async with session_scope() as session:
        for i, ts in enumerate([t0, t_same, t_next]):
            session.add(
                EventRecord(
                    vcenter_id=vid,
                    occurred_at=ts,
                    event_type="VmPoweredOnEvent",
                    message=f"m{i}",
                    vmware_key=i + 1,
                    notable_score=10,
                )
            )

    from_iso = t0.isoformat().replace("+00:00", "Z")
    to_iso = t_next.isoformat().replace("+00:00", "Z")
    q = (
        f"/api/events/rate-series?event_type={quote('VmPoweredOnEvent')}"
        f"&from={quote(from_iso)}&to={quote(to_iso)}&bucket_seconds={b}"
        f"&vcenter_id={vid}"
    )
    resp = await client.get(q)
    assert resp.status_code == 200
    data = resp.json()
    assert data["bucket_seconds"] == b
    buckets = data["buckets"]
    assert len(buckets) == 2
    assert buckets[0]["count"] == 2
    assert buckets[1]["count"] == 1


@pytest.mark.asyncio
async def test_rate_series_rejects_from_after_to(client: AsyncClient) -> None:
    t0 = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=1)
    q = (
        f"/api/events/rate-series?event_type=Foo"
        f"&from={quote(t1.isoformat().replace('+00:00', 'Z'))}"
        f"&to={quote(t0.isoformat().replace('+00:00', 'Z'))}"
        f"&bucket_seconds=300"
    )
    resp = await client.get(q)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_event_types_ordered_by_recent(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "types-vc",
            "host": "vc2.example",
            "port": 443,
            "username": "u",
            "password": "p",
            "is_enabled": True,
        },
    )
    assert r.status_code == 201
    vid = uuid.UUID(r.json()["id"])
    base = datetime(2025, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

    async with session_scope() as session:
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=base,
                event_type="OlderType",
                message="a",
                vmware_key=1,
                notable_score=1,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=base + timedelta(days=1),
                event_type="NewerType",
                message="b",
                vmware_key=2,
                notable_score=1,
            )
        )

    resp = await client.get(f"/api/events/event-types?vcenter_id={vid}")
    assert resp.status_code == 200
    types = resp.json()["event_types"]
    assert types[0] == "NewerType"
    assert "OlderType" in types
