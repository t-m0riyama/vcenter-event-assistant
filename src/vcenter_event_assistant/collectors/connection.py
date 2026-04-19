"""pyVmomi connection helpers (blocking; call via asyncio.to_thread)."""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from urllib.parse import urlparse

from pyVim.connect import Disconnect, SmartConnect


@dataclass(frozen=True, slots=True)
class ConnectionInfo:
    """Return object for connection test."""

    product_name: str
    product_version: str
    api_version: str
    instance_uuid: str


def parse_proxy_url(url: str | None) -> tuple[str | None, int | None]:
    """Parse a proxy URL into (host, port). Returns (None, None) if url is None or empty."""
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
    port: int,
    username: str,
    password: str,
    proxy_url: str | None = None,
):
    """Establish a vCenter session. Caller must Disconnect(si)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    proxy_host, proxy_port = parse_proxy_url(proxy_url)
    kwargs: dict = dict(
        host=host, user=username, pwd=password, port=port, sslContext=ctx,
    )
    if proxy_host is not None:
        kwargs["httpProxyHost"] = proxy_host
        kwargs["httpProxyPort"] = proxy_port
    return SmartConnect(**kwargs)


def disconnect(si) -> None:
    Disconnect(si)


def read_connection_info(si) -> ConnectionInfo:
    content = si.RetrieveContent()
    about = content.about
    return ConnectionInfo(
        product_name=about.name or "",
        product_version=about.version or "",
        api_version=about.apiVersion or "",
        instance_uuid=about.instanceUuid or "",
    )
