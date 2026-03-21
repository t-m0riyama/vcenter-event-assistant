"""pyVmomi connection helpers (blocking; call via asyncio.to_thread)."""

from __future__ import annotations

import ssl
from dataclasses import dataclass

from pyVim.connect import Disconnect, SmartConnect


@dataclass(frozen=True, slots=True)
class ConnectionInfo:
    """Return object for connection test."""

    product_name: str
    product_version: str
    api_version: str
    instance_uuid: str


def connect_vcenter(*, host: str, port: int, username: str, password: str):
    """Establish a vCenter session. Caller must Disconnect(si)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return SmartConnect(host=host, user=username, pwd=password, port=port, sslContext=ctx)


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
