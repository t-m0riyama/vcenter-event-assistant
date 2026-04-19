"""Tests for proxy support in connection.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from vcenter_event_assistant.collectors.connection import connect_vcenter, parse_proxy_url


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
        assert kwargs.get("httpProxyHost") is None

    @patch("vcenter_event_assistant.collectors.connection.SmartConnect")
    def test_with_proxy_url(self, mock_sc: MagicMock) -> None:
        mock_sc.return_value = MagicMock()
        connect_vcenter(
            host="vc", port=443, username="u", password="p",
            proxy_url="http://proxy.local:3128",
        )
        _, kwargs = mock_sc.call_args
        assert kwargs["httpProxyHost"] == "proxy.local"
        assert kwargs["httpProxyPort"] == 3128
