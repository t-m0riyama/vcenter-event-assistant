"""pyVmomi 接続ヘルパー（ブロッキング; ``asyncio.to_thread`` 経由で呼び出す）。

vCenter への SmartConnect / Disconnect と接続テスト用情報の取得を担う。
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from urllib.parse import urlparse

from pyVim.connect import Disconnect, SmartConnect


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


def connect_vcenter(
    *,
    host: str,
    protocol: str = "https",
    port: int,
    username: str,
    password: str,
    proxy_url: str | None = None,
):
    """vCenter セッションを確立する。呼び出し元で ``Disconnect(si)`` すること。"""
    if protocol not in {"https", "http"}:
        raise ValueError("protocol must be 'https' or 'http'")
    proxy_host, proxy_port = parse_proxy_url(proxy_url)
    kwargs: dict = dict(host=host, user=username, pwd=password, port=port, protocol=protocol)
    if protocol == "https":
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["sslContext"] = ctx
    if proxy_host is not None:
        kwargs["httpProxyHost"] = proxy_host
        kwargs["httpProxyPort"] = proxy_port
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
