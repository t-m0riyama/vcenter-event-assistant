"""vCenter API CRUD."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from vcenter_event_assistant.db.models import EventRecord
from vcenter_event_assistant.db.session import session_scope


@pytest.mark.asyncio
async def test_vcenter_create_rejects_password_with_storage_prefix(client: AsyncClient) -> None:
    """暗号化ストレージ形式のプレフィックス ``enc:`` で始まるパスワードは拒否する。"""
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "bad-password",
            "host": "vc.example.local",
            "protocol": "https",
            "port": 443,
            "username": "admin",
            "password": "enc:looks-like-ciphertext",
            "is_enabled": True,
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_vcenter_patch_rejects_password_with_storage_prefix(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "patch-target",
            "host": "vc.example.local",
            "protocol": "https",
            "port": 443,
            "username": "admin",
            "password": "secret",
            "is_enabled": True,
        },
    )
    assert r.status_code == 201
    vid = r.json()["id"]

    p = await client.patch(
        f"/api/vcenters/{vid}",
        json={"password": "enc:bad"},
    )
    assert p.status_code == 422


@pytest.mark.asyncio
async def test_vcenter_crud(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "lab",
            "host": "vcenter.example.local",
            "protocol": "https",
            "port": 443,
            "username": "admin",
            "password": "secret",
            "is_enabled": True,
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "lab"
    assert body["protocol"] == "https"
    assert "password" not in body

    list_r = await client.get("/api/vcenters")
    assert list_r.status_code == 200
    assert len(list_r.json()) == 1

    vid = body["id"]
    g = await client.get(f"/api/vcenters/{vid}")
    assert g.status_code == 200

    p = await client.patch(f"/api/vcenters/{vid}", json={"is_enabled": False})
    assert p.status_code == 200
    assert p.json()["is_enabled"] is False

    d = await client.delete(f"/api/vcenters/{vid}")
    assert d.status_code == 204


@pytest.mark.asyncio
async def test_vcenter_patch_multiple_fields(client: AsyncClient) -> None:
    """PATCH で name/host/port/username/password を一括更新できる。"""
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "before",
            "host": "old.example.local",
            "protocol": "https",
            "port": 443,
            "username": "admin",
            "password": "secret",
            "is_enabled": True,
        },
    )
    assert r.status_code == 201
    vid = r.json()["id"]

    p = await client.patch(
        f"/api/vcenters/{vid}",
        json={
            "name": "after",
            "host": "new.example.local",
            "protocol": "http",
            "port": 8443,
            "username": "newadmin",
            "password": "newsecret",
        },
    )
    assert p.status_code == 200
    body = p.json()
    assert body["name"] == "after"
    assert body["host"] == "new.example.local"
    assert body["protocol"] == "http"
    assert body["port"] == 8443
    assert body["username"] == "newadmin"
    assert "password" not in body


@pytest.mark.asyncio
async def test_vcenter_create_defaults_protocol_to_https(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "default-protocol",
            "host": "default.example.local",
            "port": 443,
            "username": "admin",
            "password": "secret",
            "is_enabled": True,
        },
    )
    assert r.status_code == 201
    assert r.json()["protocol"] == "https"


@pytest.mark.asyncio
async def test_vcenter_delete_cascades_related_events(client: AsyncClient) -> None:
    """関連 events がある vCenter も DELETE できる（DB ON DELETE CASCADE + passive_deletes）。"""
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "with-events",
            "host": "vc.example.local",
            "protocol": "https",
            "port": 443,
            "username": "admin",
            "password": "secret",
            "is_enabled": True,
        },
    )
    assert r.status_code == 201
    vid = uuid.UUID(r.json()["id"])

    async with session_scope() as session:
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=datetime.now(timezone.utc),
                event_type="com.vmware.test",
                message="bench event",
                vmware_key=42,
                notable_score=1,
            )
        )

    d = await client.delete(f"/api/vcenters/{vid}")
    assert d.status_code == 204

    list_r = await client.get("/api/vcenters")
    assert list_r.status_code == 200
    assert list_r.json() == []
