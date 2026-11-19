"""Transport for the Linux plugin services. Only the app can initiate a request."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import struct
from pathlib import Path
from typing import Any

ROLE_UIDS = {"app": 1000, "worker": 1001, "installer": 1002, "builder": 1003}
HEADER_LIMIT = 128 * 1024
ARTIFACT_LIMIT = 1024 * 1024 * 1024
FILE_LIMIT = 50_000
CHUNK_SIZE = 64 * 1024
CONNECT_TIMEOUT = 5
WORKER_SESSION_READY = {"session": "ready"}
WORKER_SESSION_UNAVAILABLE = {"session": "unavailable"}


class PluginServiceError(RuntimeError):
    pass


def socket_path(root: str, role: str) -> Path:
    return Path(root) / role / "service.sock"


def role_uid(role: str) -> int:
    uids = {
        name: int(os.environ.get(f"VEA_PLUGIN_{name.upper()}_UID", default))
        for name, default in ROLE_UIDS.items()
    }
    if len(set(uids.values())) != len(uids) or any(
        not 0 < uid < 2**32 - 1 for uid in uids.values()
    ):
        raise PluginServiceError("configure a distinct non-root UID for each plugin service role")
    return uids[role]


def verify_local_uid(role: str) -> None:
    if not hasattr(socket, "SO_PEERCRED"):
        raise PluginServiceError("plugin service isolation requires Linux")
    if os.getuid() != role_uid(role) or os.geteuid() != os.getuid():
        raise PluginServiceError(f"run the {role} service under its dedicated non-root UID")


def verify_peer(sock: Any, role: str) -> None:
    if not hasattr(socket, "SO_PEERCRED"):
        raise PluginServiceError("plugin service isolation requires Linux")
    credentials = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
    _, uid, _ = struct.unpack("iII", credentials)
    expected = role_uid(role)
    if expected == 0 or uid != expected or uid == os.getuid():
        raise PluginServiceError(f"unexpected {role} service peer UID")


def encode_header(value: dict[str, Any]) -> bytes:
    encoded = json.dumps(value, separators=(",", ":")).encode() + b"\n"
    if len(encoded) > HEADER_LIMIT:
        raise PluginServiceError("plugin service request is too large")
    return encoded


async def read_header(reader: asyncio.StreamReader) -> dict[str, Any]:
    line = await reader.readline()
    if not line.endswith(b"\n") or len(line) > HEADER_LIMIT:
        raise PluginServiceError("invalid plugin service header")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise PluginServiceError("invalid plugin service header")
    return value


async def connect(
    root: str, role: str, *, limit: int = HEADER_LIMIT
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(socket_path(root, role), limit=limit),
            CONNECT_TIMEOUT,
        )
        try:
            verify_peer(writer.get_extra_info("socket"), role)
        except BaseException:
            writer.close()
            raise
    except (OSError, TimeoutError) as exc:
        raise PluginServiceError(f"plugin {role} service is unavailable") from exc
    return reader, writer
