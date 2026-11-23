"""Tests for proxy support in connection.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from vcenter_event_assistant.collectors.connection import (
    VCenterProtocolPolicyError,
    connect_vcenter,
    parse_proxy_url,
)
from vcenter_event_assistant.settings import get_settings
from vcenter_event_assistant.settings_binding import bind_settings


class TestParseProxyUrl:
    """parse_proxy_url extracts host and port from a URL string."""

    def test_none_returns_none_pair(self) -> None:
        assert parse_proxy_url(None) == (None, None)

    def test_http_url_with_port(self) -> None:
        assert parse_proxy_url("http://proxy.local:3128") == ("proxy.local", 3128)

    def test_http_url_without_port_defaults_to_80(self) -> None:
        assert parse_proxy_url("http://proxy.local") == ("proxy.local", 80)

    def test_https_url_with_port(self) -> None:
        assert parse_proxy_url("https://proxy.local:8443") == ("proxy.local", 8443)


class TestConnectVcenterProxy:
    """connect_vcenter passes proxy args to SmartConnect."""

    @patch("vcenter_event_assistant.collectors.connection.SmartConnect")
    def test_no_proxy(self, mock_sc: MagicMock) -> None:
        mock_sc.return_value = MagicMock()
        connect_vcenter(host="vc", port=443, username="u", password="p")
        _, kwargs = mock_sc.call_args
        assert kwargs["protocol"] == "https"
        assert kwargs.get("sslContext") is not None
        assert kwargs.get("httpProxyHost") is None

    @patch("vcenter_event_assistant.collectors.connection.SmartConnect")
    def test_with_proxy_url(self, mock_sc: MagicMock) -> None:
        mock_sc.return_value = MagicMock()
        connect_vcenter(
            host="vc", port=443, username="u", password="p",
            proxy_url="http://proxy.local:3128",
        )
        _, kwargs = mock_sc.call_args
        assert kwargs["protocol"] == "https"
        assert kwargs["httpProxyHost"] == "proxy.local"
        assert kwargs["httpProxyPort"] == 3128

    @patch("vcenter_event_assistant.collectors.connection.SmartConnect")
    def test_http_protocol_does_not_pass_ssl_context(self, mock_sc: MagicMock) -> None:
        mock_sc.return_value = MagicMock()
        connect_vcenter(host="vc", protocol="http", port=80, username="u", password="p")
        _, kwargs = mock_sc.call_args
        assert kwargs["protocol"] == "http"
        assert "sslContext" not in kwargs

    def test_invalid_protocol_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="protocol must be 'https' or 'http'"):
            connect_vcenter(host="vc", protocol="ftp", port=21, username="u", password="p")

    @patch("vcenter_event_assistant.collectors.connection.SmartConnect")
    @patch("vcenter_event_assistant.collectors.connection.validate_vcenter_host")
    def test_production_rejects_http_before_dns(self, dns: MagicMock, smart_connect: MagicMock) -> None:
        bind_settings(get_settings().model_copy(update={"app_env": "production"}))
        with pytest.raises(VCenterProtocolPolicyError):
            connect_vcenter(host="vc", protocol="http", port=80, username="u", password="p")
        dns.assert_not_called()
        smart_connect.assert_not_called()

    @patch("vcenter_event_assistant.collectors.connection.SmartConnect")
    def test_production_https_keeps_proxy_and_tls(self, smart_connect: MagicMock) -> None:
        bind_settings(get_settings().model_copy(update={"app_env": "production"}))
        connect_vcenter(
            host="vc", port=443, username="u", password="p",
            proxy_url="http://proxy.local:3128",
        )
        assert smart_connect.call_args.kwargs["protocol"] == "https"
        assert smart_connect.call_args.kwargs["httpProxyHost"] == "proxy.local"
        assert smart_connect.call_args.kwargs["sslContext"].check_hostname is True

    @pytest.mark.parametrize("port", [-443, 0, 443.5, 65535.9, 65536])
    @patch("vcenter_event_assistant.collectors.connection.SmartConnect")
    @patch("vcenter_event_assistant.collectors.connection.validate_vcenter_host")
    def test_invalid_stored_port_is_rejected_before_dns(
        self, dns: MagicMock, smart_connect: MagicMock, port: int | float
    ) -> None:
        with pytest.raises(ValueError, match="port must be an integer between"):
            connect_vcenter(host="vc", protocol="https", port=port, username="u", password="p")
        dns.assert_not_called()
        smart_connect.assert_not_called()


@pytest.mark.parametrize(
    "protocol, port, proxy_url",
    [
        ("http", 80, None),
        ("https", 443, None),
        ("https", 443, "http://proxy.local:3128"),
    ],
)
@patch("vcenter_event_assistant.collectors.connection.build_ssl_context")
@patch("vcenter_event_assistant.collectors.connection.SmartConnect")
def test_inventory_connection_timeout_preserves_smart_connect_arguments(
    smart_connect, mock_ssl_context, protocol, port, proxy_url
):
    params = dict(
        host="vc",
        protocol=protocol,
        port=port,
        username="u",
        password="p",
        proxy_url=proxy_url,
    )
    assert connect_vcenter(**params) is smart_connect.return_value
    previous = smart_connect.call_args.kwargs
    assert "httpConnectionTimeout" not in previous
    assert previous["protocol"] == protocol
    assert previous["port"] == port
    if protocol == "https":
        assert previous["sslContext"] is mock_ssl_context.return_value

    assert (
        connect_vcenter(**params, http_connection_timeout=30)
        is smart_connect.return_value
    )
    assert smart_connect.call_args.kwargs == {**previous, "httpConnectionTimeout": 30}
