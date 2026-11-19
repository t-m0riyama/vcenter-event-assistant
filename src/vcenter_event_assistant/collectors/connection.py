"""pyVmomi 接続ヘルパー（ブロッキング; ``asyncio.to_thread`` 経由で呼び出す）。

vCenter への SmartConnect / Disconnect と接続テスト用情報の取得を担う。
"""

from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass
from urllib.parse import urlparse

from pyVim.connect import Disconnect, SmartConnect

from vcenter_event_assistant.services.vcenter_host_validation import (
    resolve_vcenter_target,
    validate_vcenter_host,
)
from vcenter_event_assistant.settings import Settings
from vcenter_event_assistant.settings_binding import require_settings


VCENTER_HTTPS_REQUIRED = "APP_ENV=production では vCenter protocol は https のみ許可されます"


class VCenterProtocolPolicyError(ValueError):
    def __init__(self) -> None:
        super().__init__(VCENTER_HTTPS_REQUIRED)


def validate_vcenter_protocol(protocol: str, settings: Settings) -> None:
    if settings.is_production and protocol != "https":
        raise VCenterProtocolPolicyError()


@dataclass(frozen=True, slots=True)
class ConnectionInfo:
    """接続テスト API の応答に使う vCenter 製品情報。"""

    product_name: str
    product_version: str
    api_version: str
    instance_uuid: str


def parse_proxy_url(url: str | None) -> tuple[str | None, int | None]:
    """プロキシ URL を (host, port) に分解する。空の場合は (None, None)。"""
    if not url:
        return None, None
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port
    if host and port is None:
        port = 80
    return host, port


class _PinnedAddressSSLContext(ssl.SSLContext):
    """Keep the original TLS server name when pyVmomi connects to a numeric address."""

    def __new__(cls, server_name: str) -> _PinnedAddressSSLContext:
        context = super().__new__(cls, ssl.PROTOCOL_TLS_CLIENT)
        context._server_name = server_name
        return context

    def wrap_socket(
        self,
        sock: socket.socket,
        server_side: bool = False,
        do_handshake_on_connect: bool = True,
        suppress_ragged_eofs: bool = True,
        server_hostname: str | bytes | None = None,
        session: ssl.SSLSession | None = None,
    ) -> ssl.SSLSocket:
        return super().wrap_socket(
            sock, server_side, do_handshake_on_connect, suppress_ragged_eofs,
            server_hostname=self._server_name, session=session,
        )


def build_ssl_context(
    *, verify_ssl: bool, ca_bundle_path: str | None = None, server_name: str | None = None
) -> ssl.SSLContext:
    """HTTPS 接続用 ``SSLContext`` を組み立てる。"""
    ctx = (
        _PinnedAddressSSLContext(server_name)
        if server_name is not None
        else ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    )
    if verify_ssl:
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        if ca_bundle_path:
            ctx.load_verify_locations(cafile=ca_bundle_path)
        else:
            ctx.load_default_certs()
    else:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def connect_vcenter(
    *,
    host: str,
    protocol: str = "https",
    port: int,
    username: str,
    password: str,
    proxy_url: str | None = None,
    verify_ssl: bool = True,
    ca_bundle_path: str | None = None,
):
    """vCenter セッションを確立する。呼び出し元で ``Disconnect(si)`` すること。"""
    if protocol not in {"https", "http"}:
        raise ValueError("protocol must be 'https' or 'http'")
    # pyVmomi は負のポートを平文 HTTP の指定として扱う。
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("vCenter port must be an integer between 1 and 65535")
    settings = require_settings()
    validate_vcenter_protocol(protocol, settings)
    proxy_host, proxy_port = parse_proxy_url(proxy_url)
    suffixes = settings.vcenter_allowed_host_suffix_list or None
    addresses: tuple[str, ...] = ()
    if protocol == "https" and not verify_ssl and proxy_host is None:
        host, addresses = resolve_vcenter_target(host, allowed_suffixes=suffixes)
    else:
        host = validate_vcenter_host(host, allowed_suffixes=suffixes)
    kwargs: dict = dict(host=host, user=username, pwd=password, port=port, protocol=protocol)
    if protocol == "https":
        kwargs["sslContext"] = build_ssl_context(
            verify_ssl=verify_ssl,
            ca_bundle_path=ca_bundle_path,
            server_name=host if addresses else None,
        )
    if proxy_host is not None:
        kwargs["httpProxyHost"] = proxy_host
        kwargs["httpProxyPort"] = proxy_port
    if addresses:
        authority = f"[{host}]" if ":" in host else host
        kwargs["customHeaders"] = {"Host": authority if port == 443 else f"{authority}:{port}"}
        for address in addresses[:-1]:
            try:
                return SmartConnect(**{**kwargs, "host": address})
            except OSError:
                continue
        kwargs["host"] = addresses[-1]
    return SmartConnect(**kwargs)


def disconnect(si) -> None:
    """pyVmomi セッションを切断する。"""
    Disconnect(si)


def read_connection_info(si) -> ConnectionInfo:
    """接続済みセッションから vCenter 製品情報を読み取る。

    Args:
        si: ``SmartConnect`` が返した ServiceInstance。

    Returns:
        製品名・バージョン・API バージョン・インスタンス UUID。
    """
    content = si.RetrieveContent()
    about = content.about
    return ConnectionInfo(
        product_name=about.name or "",
        product_version=about.version or "",
        api_version=about.apiVersion or "",
        instance_uuid=about.instanceUuid or "",
    )


def format_connection_error_detail(
    *,
    protocol: str,
    host: str,
    port: int,
    exc: BaseException,
) -> str:
    """接続失敗メッセージを API 向けに整形する。"""
    endpoint = f"{protocol}://{host}:{port}"
    if isinstance(exc, ssl.SSLError):
        return f"SSL certificate verification failed ({endpoint}): {exc}"
    cause = exc.__cause__
    if isinstance(cause, ssl.SSLError):
        return f"SSL certificate verification failed ({endpoint}): {cause}"
    return f"Connection failed ({endpoint}): {exc!s}"
