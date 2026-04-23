"""vCenter API CRUD."""

import pytest
from httpx import AsyncClient


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
