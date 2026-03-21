"""PATCH /api/events/{id} user_comment."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from vcenter_event_assistant.db.models import EventRecord
from vcenter_event_assistant.db.session import session_scope


@pytest.mark.asyncio
async def test_patch_event_comment_then_list_returns_it(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "ev-comment",
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
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=base,
                event_type="t",
                message="m0",
                vmware_key=1,
                notable_score=10,
            )
        )

    list_r = await client.get("/api/events?limit=10")
    assert list_r.status_code == 200
    eid = list_r.json()["items"][0]["id"]
    assert list_r.json()["items"][0].get("user_comment") in (None, "")

    patch_r = await client.patch(
        f"/api/events/{eid}",
        json={"user_comment": "調査済み"},
    )
    assert patch_r.status_code == 200
    assert patch_r.json()["user_comment"] == "調査済み"

    list2 = await client.get("/api/events?limit=10")
    assert list2.status_code == 200
    assert list2.json()["items"][0]["user_comment"] == "調査済み"


@pytest.mark.asyncio
async def test_patch_event_comment_null_clears(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "ev-clear",
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
                message="m",
                vmware_key=1,
                notable_score=10,
                user_comment="x",
            )
        )

    list_r = await client.get("/api/events?limit=10")
    eid = list_r.json()["items"][0]["id"]

    patch_r = await client.patch(f"/api/events/{eid}", json={"user_comment": None})
    assert patch_r.status_code == 200
    assert patch_r.json()["user_comment"] is None


@pytest.mark.asyncio
async def test_patch_event_comment_not_found(client: AsyncClient) -> None:
    r = await client.patch("/api/events/999999", json={"user_comment": "n"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_event_comment_too_long(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "ev-long",
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
                event_type="t",
                message="m",
                vmware_key=1,
                notable_score=10,
            )
        )

    list_r = await client.get("/api/events?limit=10")
    eid = list_r.json()["items"][0]["id"]

    bad = await client.patch(
        f"/api/events/{eid}",
        json={"user_comment": "x" * 8001},
    )
    assert bad.status_code == 422
