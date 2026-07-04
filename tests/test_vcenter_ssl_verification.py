"""TLS verify_ssl サポート（3-2）。"""

from __future__ import annotations

import ssl
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

from vcenter_event_assistant.collectors.connection import (
    build_ssl_context,
    connect_vcenter,
    format_connection_error_detail,
)


class TestBuildSslContext:
    def test_verify_disabled_uses_cert_none(self) -> None:
        ctx = build_ssl_context(verify_ssl=False)
        assert ctx.verify_mode == ssl.CERT_NONE
        assert not ctx.check_hostname

    def test_verify_enabled_uses_cert_required(self) -> None:
        ctx = build_ssl_context(verify_ssl=True)
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname


class TestConnectVcenterVerifySsl:
    @patch("vcenter_event_assistant.collectors.connection.SmartConnect")
    def test_passes_verify_ssl_to_ssl_context(self, mock_sc: MagicMock) -> None:
        mock_sc.return_value = MagicMock()
        connect_vcenter(
            host="vc",
            port=443,
            username="u",
            password="p",
            verify_ssl=True,
        )
        _, kwargs = mock_sc.call_args
        ctx = kwargs["sslContext"]
        assert ctx.verify_mode == ssl.CERT_REQUIRED


class TestFormatConnectionErrorDetail:
    def test_ssl_error_message(self) -> None:
        detail = format_connection_error_detail(
            protocol="https",
            host="vc.example",
            port=443,
            exc=ssl.SSLError("certificate verify failed"),
        )
        assert "SSL certificate verification failed" in detail
        assert "https://vc.example:443" in detail


@pytest.mark.asyncio
async def test_vcenter_test_returns_502_on_ssl_error_when_verify_ssl_enabled(
    client: AsyncClient,
) -> None:
    create = await client.post(
        "/api/vcenters",
        json={
            "name": "ssl-vc",
            "host": "vc.example.local",
            "protocol": "https",
            "port": 443,
            "username": "admin",
            "password": "secret",
            "verify_ssl": True,
            "is_enabled": True,
        },
    )
    assert create.status_code == 201
    vid = create.json()["id"]

    with patch(
        "vcenter_event_assistant.api.routes.vcenters.connect_vcenter",
        side_effect=ssl.SSLError("certificate verify failed"),
    ):
        test_r = await client.get(f"/api/vcenters/{vid}/test")

    assert test_r.status_code == 502
    assert "SSL certificate verification failed" in test_r.json()["detail"]


@pytest.mark.asyncio
async def test_vcenter_test_recommends_ssl_verification_when_disabled(
    client: AsyncClient,
) -> None:
    create = await client.post(
        "/api/vcenters",
        json={
            "name": "plain-ssl-vc",
            "host": "vc.example.local",
            "protocol": "https",
            "port": 443,
            "username": "admin",
            "password": "secret",
            "verify_ssl": False,
            "is_enabled": True,
        },
    )
    assert create.status_code == 201
    vid = create.json()["id"]

    mock_info = MagicMock(
        product_name="VMware vCenter Server",
        product_version="8.0.0",
        api_version="8.0",
        instance_uuid="uuid-1",
    )
    with patch(
        "vcenter_event_assistant.api.routes.vcenters.connect_vcenter",
        return_value=MagicMock(),
    ), patch(
        "vcenter_event_assistant.api.routes.vcenters.read_connection_info",
        return_value=mock_info,
    ), patch("vcenter_event_assistant.api.routes.vcenters.disconnect"):
        test_r = await client.get(f"/api/vcenters/{vid}/test")

    assert test_r.status_code == 200
    body = test_r.json()
    assert body["ok"] is True
    assert body["recommend_ssl_verification"] is True
    assert "本番" in body["recommend_ssl_verification_message"]


@pytest.mark.asyncio
async def test_vcenter_create_defaults_verify_ssl_to_false(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "default-verify",
            "host": "default.example.local",
            "port": 443,
            "username": "admin",
            "password": "secret",
            "is_enabled": True,
        },
    )
    assert r.status_code == 201
    assert r.json()["verify_ssl"] is False
