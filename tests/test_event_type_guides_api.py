"""CRUD /api/event-type-guides."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_event_type_guides_crud(client: AsyncClient) -> None:
    lst0 = await client.get("/api/event-type-guides")
    assert lst0.status_code == 200
    assert lst0.json() == []

    post = await client.post(
        "/api/event-type-guides",
        json={
            "event_type": "vim.event.UserLoginSessionEvent",
            "general_meaning": "ユーザーがログインした",
            "typical_causes": "認証成功",
            "remediation": "問題なし",
        },
    )
    assert post.status_code == 201
    gid = post.json()["id"]
    assert post.json()["event_type"] == "vim.event.UserLoginSessionEvent"
    assert post.json()["action_required"] is False

    dup = await client.post(
        "/api/event-type-guides",
        json={"event_type": "vim.event.UserLoginSessionEvent", "general_meaning": "x"},
    )
    assert dup.status_code == 409

    bad = await client.post("/api/event-type-guides", json={"event_type": "  ", "general_meaning": "x"})
    assert bad.status_code == 422

    patch = await client.patch(
        f"/api/event-type-guides/{gid}",
        json={"general_meaning": "更新後", "typical_causes": None},
    )
    assert patch.status_code == 200
    assert patch.json()["general_meaning"] == "更新後"
    assert patch.json()["typical_causes"] is None
    assert patch.json()["remediation"] == "問題なし"

    lst = await client.get("/api/event-type-guides")
    assert lst.status_code == 200
    assert len(lst.json()) == 1

    del_r = await client.delete(f"/api/event-type-guides/{gid}")
    assert del_r.status_code == 204

    gone = await client.delete(f"/api/event-type-guides/{gid}")
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_create_event_type_guide_action_required(client: AsyncClient) -> None:
    r = await client.post(
        "/api/event-type-guides",
        json={
            "event_type": "vim.event.Foo",
            "action_required": True,
            "general_meaning": "x",
        },
    )
    assert r.status_code == 201
    assert r.json()["action_required"] is True
    gid = r.json()["id"]

    patch = await client.patch(f"/api/event-type-guides/{gid}", json={"action_required": False})
    assert patch.status_code == 200
    assert patch.json()["action_required"] is False
