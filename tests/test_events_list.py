"""GET /api/events pagination and total count."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from vcenter_event_assistant.db.models import EventRecord
from vcenter_event_assistant.db.session import session_scope


@pytest.mark.asyncio
async def test_list_events_returns_total_and_pages(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "ev-page",
            "host": "vc.example",
            "port": 443,
            "username": "u",
            "password": "p",
            "is_enabled": True,
        },
    )
    assert r.status_code == 201
    vid = uuid.UUID(r.json()["id"])
    base = datetime.now(timezone.utc)

    async with session_scope() as session:
        for i in range(5):
            session.add(
                EventRecord(
                    vcenter_id=vid,
                    occurred_at=base - timedelta(minutes=i),
                    event_type="t",
                    message=f"m{i}",
                    vmware_key=i + 1,
                    notable_score=10,
                )
            )

    r0 = await client.get("/api/events?limit=2&offset=0")
    assert r0.status_code == 200
    d0 = r0.json()
    assert d0["total"] == 5
    assert len(d0["items"]) == 2
    assert [x["message"] for x in d0["items"]] == ["m0", "m1"]
    # UTC instant explicit in JSON so browsers parse consistently (not as local time).
    assert d0["items"][0]["occurred_at"].endswith("Z")

    r1 = await client.get("/api/events?limit=2&offset=2")
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["total"] == 5
    assert len(d1["items"]) == 2
    assert [x["message"] for x in d1["items"]] == ["m2", "m3"]


@pytest.mark.asyncio
async def test_list_events_min_score_filters_total(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "ev-score",
            "host": "vc2.example",
            "port": 443,
            "username": "u",
            "password": "p",
            "is_enabled": True,
        },
    )
    assert r.status_code == 201
    vid = uuid.UUID(r.json()["id"])
    base = datetime.now(timezone.utc)

    async with session_scope() as session:
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=base,
                event_type="t",
                message="low",
                vmware_key=1,
                notable_score=10,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=base - timedelta(minutes=1),
                event_type="t",
                message="high",
                vmware_key=2,
                notable_score=50,
            )
        )

    resp = await client.get("/api/events?min_score=40")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["message"] == "high"


@pytest.mark.asyncio
async def test_list_events_message_contains_case_insensitive(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "ev-msg-filter",
            "host": "vc3.example",
            "port": 443,
            "username": "u",
            "password": "p",
            "is_enabled": True,
        },
    )
    assert r.status_code == 201
    vid = uuid.UUID(r.json()["id"])
    base = datetime.now(timezone.utc)

    async with session_scope() as session:
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=base,
                event_type="TypeA",
                message="Hello WORLD here",
                vmware_key=1,
                notable_score=10,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=base - timedelta(minutes=1),
                event_type="TypeB",
                message="other",
                vmware_key=2,
                notable_score=10,
            )
        )

    resp = await client.get("/api/events", params={"message_contains": "world"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["message"] == "Hello WORLD here"


@pytest.mark.asyncio
async def test_list_events_event_type_and_severity_contains(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "ev-type-sev",
            "host": "vc4.example",
            "port": 443,
            "username": "u",
            "password": "p",
            "is_enabled": True,
        },
    )
    assert r.status_code == 201
    vid = uuid.UUID(r.json()["id"])
    base = datetime.now(timezone.utc)

    async with session_scope() as session:
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=base,
                event_type="com.vmware.vm.poweredOn",
                message="m1",
                severity="warning",
                vmware_key=1,
                notable_score=10,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=base - timedelta(minutes=1),
                event_type="other.event",
                message="m2",
                severity="info",
                vmware_key=2,
                notable_score=10,
            )
        )

    r1 = await client.get("/api/events", params={"event_type_contains": "poweredOn"})
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["total"] == 1
    assert "poweredOn" in d1["items"][0]["event_type"]

    r2 = await client.get("/api/events", params={"severity_contains": "warn"})
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["total"] == 1
    assert d2["items"][0]["severity"] == "warning"


@pytest.mark.asyncio
async def test_list_events_comment_contains(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "ev-comment-filter",
            "host": "vc5.example",
            "port": 443,
            "username": "u",
            "password": "p",
            "is_enabled": True,
        },
    )
    assert r.status_code == 201
    vid = uuid.UUID(r.json()["id"])
    base = datetime.now(timezone.utc)

    async with session_scope() as session:
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=base,
                event_type="t",
                message="m1",
                user_comment="調査済みメモ",
                vmware_key=1,
                notable_score=10,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=base - timedelta(minutes=1),
                event_type="t",
                message="m2",
                user_comment=None,
                vmware_key=2,
                notable_score=10,
            )
        )

    resp = await client.get("/api/events", params={"comment_contains": "メモ"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["user_comment"] == "調査済みメモ"


@pytest.mark.asyncio
async def test_list_events_text_filters_with_min_score(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "ev-combo",
            "host": "vc6.example",
            "port": 443,
            "username": "u",
            "password": "p",
            "is_enabled": True,
        },
    )
    assert r.status_code == 201
    vid = uuid.UUID(r.json()["id"])
    base = datetime.now(timezone.utc)

    async with session_scope() as session:
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=base,
                event_type="alert",
                message="disk full",
                vmware_key=1,
                notable_score=60,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=base - timedelta(minutes=1),
                event_type="alert",
                message="disk full",
                vmware_key=2,
                notable_score=20,
            )
        )

    resp = await client.get(
        "/api/events",
        params={"message_contains": "disk", "min_score": 40},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["notable_score"] == 60
