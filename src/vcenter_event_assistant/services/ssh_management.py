"""Managed SSH references; private material never enters configuration responses."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from contextlib import asynccontextmanager
from uuid import UUID

from vcenter_event_assistant.db.models import SSHConnection, SSHCredential
from vcenter_event_assistant.db.session import session_scope


def fingerprint(public_key: str) -> str:
    import asyncssh

    return str(asyncssh.import_public_key(public_key).get_fingerprint("sha256"))


def connection_read(c):
    return {
        "id": str(c.id),
        "name": c.name,
        "host": c.host,
        "port": c.port,
        "username": c.username,
        "credential_id": str(c.credential_id),
        "revision": c.revision,
        "approved": bool(c.approved_key),
        "fingerprint": fingerprint(c.approved_key) if c.approved_key else None,
        "candidate_fingerprint": fingerprint(c.candidate_key)
        if c.candidate_key
        else None,
    }


def ssh_objects(value, schema, *, require_connections=False):
    if not isinstance(schema, dict):
        return
    if isinstance(value, dict):
        field = schema.get("x-vea-ssh-connection")
        legacy_connection = all(
            value.get(name)
            for name in ("host", "username", "private_key_file", "known_hosts_file")
        )
        if field and require_connections and not value.get(field) and not legacy_connection:
            raise ValueError("各収集対象のSSH接続先を選択して保存してください。")
        if field and value.get(field):
            yield value, str(value[field])
        for key, child in schema.get("properties", {}).items():
            if key in value:
                yield from ssh_objects(value[key], child, require_connections=require_connections)
    elif isinstance(value, list):
        for item in value:
            yield from ssh_objects(item, schema.get("items", {}), require_connections=require_connections)


async def reference_digest(session, config, schema):
    references = []
    for _, identifier in ssh_objects(config, schema, require_connections=True):
        c = await session.get(SSHConnection, UUID(identifier))
        if c is None or not c.approved_key:
            raise ValueError("SSH接続先が未登録、またはホスト鍵が未承認です。")
        references.append([str(c.id), c.revision, c.approved_key, str(c.credential_id)])
    return hashlib.sha256(
        json.dumps([config, references], sort_keys=True).encode()
    ).hexdigest()


def cleanup_stale_ssh_files():
    root = Path(tempfile.gettempdir())
    for path in root.glob("vea-ssh-*"):
        if path.is_symlink() or not path.is_dir() or path.stat().st_uid != os.getuid():
            continue
        match = re.fullmatch(r"vea-ssh-(\d+)", path.name)
        if not match:
            continue
        if int(match[1]) == os.getpid():
            shutil.rmtree(path, ignore_errors=True)
            continue
        try:
            os.kill(int(match[1]), 0)
        except ProcessLookupError:
            shutil.rmtree(path, ignore_errors=True)
        except PermissionError:
            pass


@asynccontextmanager
async def materialize_ssh(settings, config, schema, target_id=None):
    """Files live for exactly one worker request, including timeout/exception paths."""
    resolved = copy.deepcopy(config)
    objects = list(ssh_objects(resolved, schema, require_connections=True))
    if not objects:
        yield resolved
        return
    root = Path(tempfile.gettempdir()) / f"vea-ssh-{os.getpid()}"
    root.mkdir(mode=0o700, exist_ok=True)
    if root.is_symlink() or root.stat().st_uid != os.getuid():
        raise ValueError("SSH一時ディレクトリを利用できません。")
    root.chmod(0o700)
    directory = Path(tempfile.mkdtemp(prefix="run-", dir=root))
    try:
        async with session_scope(settings=settings) as session:
            for index, (obj, identifier) in enumerate(objects):
                if (
                    target_id
                    and obj.get("vcenter_id")
                    and obj["vcenter_id"] != str(target_id)
                ):
                    continue
                c = await session.get(SSHConnection, UUID(identifier))
                if not c or not c.approved_key:
                    raise ValueError("SSH接続先のホスト鍵を承認してください。")
                credential = await session.get(SSHCredential, c.credential_id)
                if not credential:
                    raise ValueError("SSH鍵が見つかりません。")
                key_path = directory / f"{index}.key"
                known_path = directory / f"{index}.known_hosts"
                host_pattern = c.host if c.port == 22 else f"[{c.host}]:{c.port}"
                for path, content in (
                    (key_path, credential.private_key),
                    (
                        known_path,
                        f"{host_pattern} {c.approved_key.strip()}\n",
                    ),
                ):
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
                    with os.fdopen(fd, "w") as output:
                        output.write(content)
                obj.update(
                    host=c.host,
                    port=c.port,
                    username=c.username,
                    private_key_file=str(key_path),
                    known_hosts_file=str(known_path),
                )
        yield resolved
    finally:
        shutil.rmtree(directory, ignore_errors=True)
