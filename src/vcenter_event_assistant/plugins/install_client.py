"""Submit plugin installs to a separate UID and receive a bounded file stream."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vcenter_event_assistant.plugins.service_protocol import (
    ARTIFACT_LIMIT,
    CHUNK_SIZE,
    FILE_LIMIT,
    PluginServiceError,
    connect,
    encode_header,
    read_header,
)
from vcenter_event_assistant.plugins.subprocess_env import (
    INSTALLER_JOB_ENV_VARS,
    PROXY_ENV_VARS,
    url_has_credentials,
)

if TYPE_CHECKING:
    from vcenter_event_assistant.settings import Settings


def _route(
    settings: Settings, source: str, from_index: bool
) -> tuple[str, dict[str, Any]]:
    index = settings.plugin_index_url
    proxies = {key: os.environ[key] for key in PROXY_ENV_VARS if os.environ.get(key)}
    no_proxy = {
        key: os.environ[key] for key in ("NO_PROXY", "no_proxy") if os.environ.get(key)
    }
    build_with_index = (
        not url_has_credentials(index)
        and not any(url_has_credentials(value) for value in (*proxies.values(), *no_proxy.values()))
        and (not (index or proxies) or settings.plugin_allow_unauthenticated_build_endpoints)
    )
    local_sdist = not from_index and source.endswith(".tar.gz")
    use_index = from_index or (
        settings.plugin_allow_index_install and (not local_sdist or build_with_index)
    )
    if local_sdist or (use_index and build_with_index):
        role = "builder"
    else:
        role = "installer"

    return role, {
        "from_index": from_index,
        "use_index": use_index,
        "index": index if use_index else None,
        "proxies": {**proxies, **no_proxy} if use_index else {},
        "uv_options": {
            key: os.environ[key] for key in INSTALLER_JOB_ENV_VARS if key in os.environ
        },
    }


def _relative_path(raw: Any) -> Path:
    if not isinstance(raw, str) or not raw or len(raw) > 4096 or "\\" in raw or "\0" in raw:
        raise PluginServiceError("invalid plugin artifact path")
    if any(part in ("", ".", "..") for part in raw.split("/")):
        raise PluginServiceError("invalid plugin artifact path")
    return Path(raw)


async def receive_artifact(reader: asyncio.StreamReader, destination: Path) -> None:
    seen: set[Path] = set()
    total = 0
    while True:
        frame = await read_header(reader)
        if frame == {"complete": True}:
            return
        if "error" in frame:
            raise PluginServiceError("plugin installation service failed")
        directory = set(frame) == {"directory"}
        if not directory and set(frame) != {"file", "size", "executable"}:
            raise PluginServiceError("invalid plugin artifact frame")
        path = _relative_path(frame["directory" if directory else "file"])
        if path in seen or len(seen) >= FILE_LIMIT:
            raise PluginServiceError("duplicate or excessive plugin artifact entries")
        seen.add(path)
        target = destination / path
        if directory:
            target.mkdir()
            target.chmod(0o755)
            continue
        size = frame["size"]
        executable = frame["executable"]
        if type(size) is not int or size < 0 or type(executable) is not bool:
            raise PluginServiceError("invalid plugin artifact file")
        total += size
        if total > ARTIFACT_LIMIT:
            raise PluginServiceError("plugin artifact is too large")
        with target.open("xb") as output:
            while size:
                chunk = await reader.readexactly(min(size, CHUNK_SIZE))
                output.write(chunk)
                size -= len(chunk)
        target.chmod(0o755 if executable else 0o644)


async def install_via_service(
    settings: Settings, source: str, *, from_index: bool, destination: Path, timeout: float,
) -> None:
    root = settings.plugin_service_socket_dir
    assert root is not None
    role, request = _route(settings, source, from_index)
    async with asyncio.timeout(timeout):
        reader, writer = await connect(root, role)
        try:
            if from_index:
                writer.write(encode_header({**request, "source": source}))
                await writer.drain()
            else:
                with Path(source).open("rb") as package:
                    writer.write(encode_header({
                        **request, "source": Path(source).name,
                        "size": os.fstat(package.fileno()).st_size,
                    }))
                    while chunk := package.read(CHUNK_SIZE):
                        writer.write(chunk)
                        await writer.drain()
            await receive_artifact(reader, destination)
        except (OSError, EOFError, ValueError) as exc:
            raise PluginServiceError("plugin installation service transfer failed") from exc
        finally:
            writer.close()
