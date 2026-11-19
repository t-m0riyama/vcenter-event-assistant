"""Files forwarded over the authenticated worker connection for one request."""

from __future__ import annotations

import base64
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_MAX_FILE_BYTES = 1024 * 1024


def encode_file(content: bytes) -> str:
    if len(content) > _MAX_FILE_BYTES:
        raise ValueError("plugin request file is too large")
    return base64.b64encode(content).decode("ascii")


def read_file(path: str) -> str:
    with Path(path).open("rb") as source:
        return encode_file(source.read(_MAX_FILE_BYTES + 1))


def write_file(path: Path, encoded: str) -> None:
    content = base64.b64decode(encoded, validate=True)
    if len(content) > _MAX_FILE_BYTES:
        raise ValueError("plugin request file is too large")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    with os.fdopen(fd, "wb") as file:
        file.write(content)


@contextmanager
def materialize_request_files(files: dict[str, str]) -> Iterator[dict[str, str]]:
    if not files:
        yield {}
        return
    with tempfile.TemporaryDirectory(prefix="request-files-") as directory:
        paths: dict[str, str] = {}
        for number, (source, content) in enumerate(files.items()):
            path = Path(directory) / str(number)
            write_file(path, content)
            paths[source] = str(path)
        yield paths


def replace_ssh_paths(value: Any, paths: dict[str, str]) -> Any:
    if isinstance(value, list):
        return [replace_ssh_paths(item, paths) for item in value]
    if isinstance(value, dict):
        return {
            key: paths.get(item, item)
            if key in ("private_key_file", "known_hosts_file") and isinstance(item, str)
            else replace_ssh_paths(item, paths)
            for key, item in value.items()
        }
    return value
