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
