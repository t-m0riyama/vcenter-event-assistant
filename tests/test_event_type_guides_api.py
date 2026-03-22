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


@pytest.mark.asyncio
async def test_event_type_guides_import_duplicate_event_type_returns_400(client: AsyncClient) -> None:
    r = await client.post(
        "/api/event-type-guides/import",
        json={
            "overwrite_existing": True,
            "delete_guides_not_in_import": False,
            "guides": [
                {"event_type": "vim.event.A", "general_meaning": "a"},
                {"event_type": "vim.event.A", "general_meaning": "b"},
            ],
        },
    )
    assert r.status_code == 400
    assert "duplicate" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_event_type_guides_import_overwrite_and_delete_orphans(client: AsyncClient) -> None:
    a = await client.post(
        "/api/event-type-guides",
        json={"event_type": "orphan.Type", "general_meaning": "o"},
    )
    assert a.status_code == 201
    b = await client.post(
        "/api/event-type-guides",
        json={"event_type": "keep.Type", "general_meaning": "k"},
    )
    assert b.status_code == 201

    imp = await client.post(
        "/api/event-type-guides/import",
        json={
            "overwrite_existing": True,
            "delete_guides_not_in_import": True,
            "guides": [
                {
                    "event_type": "keep.Type",
                    "general_meaning": "updated",
                    "typical_causes": None,
                    "remediation": None,
                    "action_required": True,
                },
            ],
        },
    )
    assert imp.status_code == 200
    assert imp.json()["guides_count"] == 1

    lst = await client.get("/api/event-type-guides")
    assert lst.status_code == 200
    rows = lst.json()
    assert len(rows) == 1
    assert rows[0]["event_type"] == "keep.Type"
    assert rows[0]["general_meaning"] == "updated"
    assert rows[0]["action_required"] is True


@pytest.mark.asyncio
async def test_event_type_guides_import_skip_overwrite_keeps_text(client: AsyncClient) -> None:
    created = await client.post(
        "/api/event-type-guides",
        json={"event_type": "vim.event.SkipGuide", "general_meaning": "original"},
    )
    assert created.status_code == 201

    imp = await client.post(
        "/api/event-type-guides/import",
        json={
            "overwrite_existing": False,
            "delete_guides_not_in_import": False,
            "guides": [
                {
                    "event_type": "vim.event.SkipGuide",
                    "general_meaning": "new",
                    "action_required": True,
                },
            ],
        },
    )
    assert imp.status_code == 200

    lst = await client.get("/api/event-type-guides")
    row = next(r for r in lst.json() if r["event_type"] == "vim.event.SkipGuide")
    assert row["general_meaning"] == "original"
    assert row["action_required"] is False


@pytest.mark.asyncio
async def test_event_type_guides_import_empty_file_deletes_all_when_flag(client: AsyncClient) -> None:
    await client.post("/api/event-type-guides", json={"event_type": "t.only", "general_meaning": "x"})
    imp = await client.post(
        "/api/event-type-guides/import",
        json={
            "overwrite_existing": True,
            "delete_guides_not_in_import": True,
            "guides": [],
        },
    )
    assert imp.status_code == 200
    assert imp.json()["guides_count"] == 0
    lst = await client.get("/api/event-type-guides")
    assert lst.json() == []
