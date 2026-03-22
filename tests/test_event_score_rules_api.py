"""CRUD /api/event-score-rules and notable_score recalculation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from vcenter_event_assistant.db.models import EventRecord
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.rules.notable import final_notable_score


@pytest.mark.asyncio
async def test_event_score_rules_crud_recalculates_events(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "score-rules-vc",
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
    et = "UserLoginSessionEvent"
    msg = "hello"

    async with session_scope() as session:
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=base,
                event_type=et,
                message=msg,
                severity="info",
                vmware_key=1,
                notable_score=0,
            )
        )

    post = await client.post(
        "/api/event-score-rules",
        json={"event_type": et, "score_delta": 25},
    )
    assert post.status_code == 201
    rule_id = post.json()["id"]
    assert post.json()["score_delta"] == 25

    expected = final_notable_score(
        event_type=et,
        severity="info",
        message=msg,
        score_delta=25,
    )
    ev = await client.get("/api/events?limit=10")
    assert ev.status_code == 200
    assert ev.json()["items"][0]["notable_score"] == expected

    dup = await client.post(
        "/api/event-score-rules",
        json={"event_type": et, "score_delta": 1},
    )
    assert dup.status_code == 409

    patch = await client.patch(f"/api/event-score-rules/{rule_id}", json={"score_delta": -10})
    assert patch.status_code == 200
    assert patch.json()["score_delta"] == -10

    expected2 = final_notable_score(
        event_type=et,
        severity="info",
        message=msg,
        score_delta=-10,
    )
    ev2 = await client.get("/api/events?limit=10")
    assert ev2.json()["items"][0]["notable_score"] == expected2

    del_r = await client.delete(f"/api/event-score-rules/{rule_id}")
    assert del_r.status_code == 204

    expected3 = final_notable_score(
        event_type=et,
        severity="info",
        message=msg,
        score_delta=0,
    )
    ev3 = await client.get("/api/events?limit=10")
    assert ev3.json()["items"][0]["notable_score"] == expected3

    lst = await client.get("/api/event-score-rules")
    assert lst.status_code == 200
    assert lst.json() == []


@pytest.mark.asyncio
async def test_event_score_rules_import_duplicate_event_type_returns_400(client: AsyncClient) -> None:
    r = await client.post(
        "/api/event-score-rules/import",
        json={
            "overwrite_existing": True,
            "delete_rules_not_in_import": False,
            "rules": [
                {"event_type": "vim.event.A", "score_delta": 1},
                {"event_type": "vim.event.A", "score_delta": 2},
            ],
        },
    )
    assert r.status_code == 400
    assert "duplicate" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_event_score_rules_import_overwrite_and_delete_orphans(client: AsyncClient) -> None:
    a = await client.post("/api/event-score-rules", json={"event_type": "orphan.Type", "score_delta": 5})
    assert a.status_code == 201
    b = await client.post("/api/event-score-rules", json={"event_type": "keep.Type", "score_delta": 3})
    assert b.status_code == 201

    imp = await client.post(
        "/api/event-score-rules/import",
        json={
            "overwrite_existing": True,
            "delete_rules_not_in_import": True,
            "rules": [{"event_type": "keep.Type", "score_delta": 99}],
        },
    )
    assert imp.status_code == 200
    data = imp.json()
    assert data["rules_count"] == 1
    assert data["events_updated"] >= 0

    lst = await client.get("/api/event-score-rules")
    assert lst.status_code == 200
    rows = lst.json()
    assert len(rows) == 1
    assert rows[0]["event_type"] == "keep.Type"
    assert rows[0]["score_delta"] == 99


@pytest.mark.asyncio
async def test_event_score_rules_import_skip_overwrite_keeps_delta(client: AsyncClient) -> None:
    created = await client.post(
        "/api/event-score-rules",
        json={"event_type": "vim.event.SkipMe", "score_delta": 7},
    )
    assert created.status_code == 201

    imp = await client.post(
        "/api/event-score-rules/import",
        json={
            "overwrite_existing": False,
            "delete_rules_not_in_import": False,
            "rules": [{"event_type": "vim.event.SkipMe", "score_delta": 50}],
        },
    )
    assert imp.status_code == 200

    lst = await client.get("/api/event-score-rules")
    row = next(r for r in lst.json() if r["event_type"] == "vim.event.SkipMe")
    assert row["score_delta"] == 7


@pytest.mark.asyncio
async def test_event_score_rules_import_empty_file_deletes_all_when_flag(client: AsyncClient) -> None:
    await client.post("/api/event-score-rules", json={"event_type": "t.only", "score_delta": 1})
    imp = await client.post(
        "/api/event-score-rules/import",
        json={
            "overwrite_existing": True,
            "delete_rules_not_in_import": True,
            "rules": [],
        },
    )
    assert imp.status_code == 200
    assert imp.json()["rules_count"] == 0
    lst = await client.get("/api/event-score-rules")
    assert lst.json() == []
