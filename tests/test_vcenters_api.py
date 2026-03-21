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
            "port": 443,
            "username": "admin",
            "password": "secret",
            "is_enabled": True,
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "lab"
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
