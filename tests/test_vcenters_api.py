"""vCenter API CRUD."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

from vcenter_event_assistant.collectors.connection import VCENTER_HTTPS_REQUIRED
from vcenter_event_assistant.db.models import EventRecord, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.settings import get_settings
from vcenter_event_assistant.settings_binding import bind_settings


async def test_production_warns_about_invalid_vcenter_transports_and_allows_migration(
    client: AsyncClient, open_client, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from vcenter_event_assistant.main import create_app, lifespan

    def body(name: str, *, enabled: bool) -> dict:
        return {
            "name": name, "host": "vc.example.com", "protocol": "http", "port": 80,
            "username": "vcenter-user", "password": "do-not-log-vcenter-password",
            "is_enabled": enabled,
        }

    created = await client.post("/api/vcenters", json=body("legacy", enabled=True))
    assert created.status_code == 201, created.text
    identifier = created.json()["id"]
    disabled = await client.post("/api/vcenters", json=body("legacy-disabled", enabled=False))
    assert disabled.status_code == 201, disabled.text
    https_ids = {port: uuid.uuid4() for port in (-443, 443.5, 443)}
    async with session_scope() as session:
        session.add_all([
            VCenter(id=identifier, **dict(body(f"https-{port}", enabled=True), protocol="https", port=port))
            for port, identifier in https_ids.items()
        ])

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("VEA_SECRET_KEY", "test-production-key")
    monkeypatch.setenv("VEA_ALLOW_PLAINTEXT_PASSWORDS", "false")
    monkeypatch.setenv("VCENTER_ALLOWED_HOST_SUFFIXES", "example.com")
    monkeypatch.setenv("VEA_PLUGIN_MANAGEMENT_ENABLED", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    get_settings.cache_clear()
    app = create_app()
    startup_logger = logging.getLogger("vcenter_event_assistant.security_startup")
    monkeypatch.setattr(startup_logger, "handlers", [*startup_logger.handlers, caplog.handler])
    smart_connect = MagicMock()
    smart_connect.return_value.RetrieveContent.return_value.about = MagicMock(
        fullName="VMware vCenter Server", version="8.0", apiVersion="8.0", instanceUuid="vc-uuid",
    )
    monkeypatch.setattr("vcenter_event_assistant.collectors.connection.SmartConnect", smart_connect)
    monkeypatch.setattr("vcenter_event_assistant.api.routes.vcenters.disconnect", MagicMock())

    async with open_client("admin", app=app, username="prod-admin") as prod:
        async with lifespan(app):
            assert f"vcenter_id={identifier} enabled=True" in caplog.text
            assert f"vcenter_id={disabled.json()['id']} enabled=False" in caplog.text
            for port in (-443, 443.5):
                assert f"vCenter requires a valid port in production: vcenter_id={https_ids[port]} enabled=True" in caplog.text
            assert str(https_ids[443]) not in caplog.text
            assert "do-not-log-vcenter-password" not in caplog.text
            with monkeypatch.context() as patch:
                dns = MagicMock(side_effect=AssertionError("must reject HTTP before DNS"))
                patch.setattr("vcenter_event_assistant.services.vcenter_host_validation.socket.getaddrinfo", dns)
                test_response = await prod.get(f"/api/vcenters/{identifier}/test")
                hosts_response = await prod.get(f"/api/plugins/vcenters/{identifier}/hosts")
                assert test_response.status_code == 400, test_response.text
                assert hosts_response.status_code == 422, hosts_response.text
                assert test_response.json()["detail"] == hosts_response.json()["detail"] == VCENTER_HTTPS_REQUIRED
                dns.assert_not_called()
                smart_connect.assert_not_called()
            assert (await prod.post("/api/vcenters", json=body("new-http", enabled=True))).status_code == 400
            assert (await prod.patch(f"/api/vcenters/{identifier}", json={"protocol": "http"})).status_code == 400
            repaired = await prod.patch(f"/api/vcenters/{https_ids[443.5]}", json={"port": 443})
            assert repaired.status_code == 200 and repaired.json()["port"] == 443, repaired.text
            assert (await prod.get("/api/vcenters")).status_code == 200
            migrated = await prod.patch(
                f"/api/vcenters/{identifier}", json={"protocol": "https", "port": 443, "verify_ssl": True}
            )
            assert migrated.status_code == 200, migrated.text
            tested = await prod.get(f"/api/vcenters/{identifier}/test")
            assert tested.status_code == 200 and tested.json()["ok"], tested.text
            assert smart_connect.call_args.kwargs["protocol"] == "https"


@pytest.mark.asyncio
async def test_vcenter_create_rejects_private_ip_host(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "ssrf",
            "host": "169.254.169.254",
            "protocol": "https",
            "port": 443,
            "username": "admin",
            "password": "secret",
            "is_enabled": True,
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_vcenter_create_rejects_without_password_storage_allowed(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VEA_ALLOW_PLAINTEXT_PASSWORDS", raising=False)
    monkeypatch.delenv("VEA_SECRET_KEY", raising=False)
    get_settings.cache_clear()
    bind_settings(get_settings())

    r = await client.post(
        "/api/vcenters",
        json={
            "name": "no-key",
            "host": "vc.example.local",
            "protocol": "https",
            "port": 443,
            "username": "admin",
            "password": "secret",
            "is_enabled": True,
        },
    )
    assert r.status_code == 503


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
