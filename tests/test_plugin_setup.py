"""Managed onboarding must not expose secrets, apply drafts, or advance cursors early."""

from dataclasses import replace
from uuid import UUID

import asyncssh
import pytest
from sqlalchemy import select, text

from vcenter_event_assistant_plugin_api import (
    CollectorManifest,
    SetupAction,
    SetupCheck,
    SetupResult,
    CollectionBatch,
)
from vcenter_event_assistant.db.models import CollectorPluginSetting, SSHCredential
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.plugins.config import CollectorConfig
from vcenter_event_assistant.plugins.registry import (
    CollectorRegistry,
    CollectorRegistration,
    get_collector_registry,
    set_collector_registry,
)
from vcenter_event_assistant.settings import get_settings
from vcenter_event_assistant.settings_binding import bind_settings
from vcenter_event_assistant.services.ssh_management import materialize_ssh

SCHEMA = {
    "type": "object",
    "required": ["targets"],
    "additionalProperties": False,
    "properties": {
        "targets": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "x-vea-ssh-connection": "ssh_connection_id",
                "required": ["vcenter_id", "ssh_connection_id"],
                "properties": {
                    "vcenter_id": {"type": "string", "x-vea-widget": "vcenter"},
                    "ssh_connection_id": {
                        "type": "string",
                        "x-vea-widget": "ssh-connection",
                    },
                },
            },
        }
    },
}


class ExamplePlugin:
    manifest = CollectorManifest(
        "example.setup",
        "Example setup",
        "1.0",
        configuration_schema=SCHEMA,
        setup_actions=(SetupAction("test", "接続テスト", True),),
    )
    fail_start = False

    async def start(self):
        if self.fail_start:
            raise RuntimeError("start fails")

    async def stop(self):
        pass

    async def collect(self, context):
        return CollectionBatch()

    async def setup(self, context, action):
        from pathlib import Path

        assert action == "test"
        assert context.previous_cursor is None
        target = context.config["targets"][0]
        assert Path(target["private_key_file"]).is_file()
        return SetupResult(
            (SetupCheck("example", "設定とSSH参照", True),), samples=({"value": 42},)
        )


@pytest.fixture
async def setup_enabled(monkeypatch):
    monkeypatch.setenv("VEA_PLUGIN_MANAGEMENT_ENABLED", "true")
    monkeypatch.setenv("VEA_SECRET_KEY", "setup-test-encryption-key")
    get_settings.cache_clear()
    bind_settings(get_settings())
    plugin = ExamplePlugin()
    registration = CollectorRegistration(
        plugin.manifest.id, plugin, "example", CollectorConfig(False, 60), "disabled"
    )
    set_collector_registry(CollectorRegistry({plugin.manifest.id: registration}))

    def build(settings, *, generation, db_overrides):
        cfg = db_overrides[plugin.manifest.id]
        r = replace(
            registration,
            status="enabled",
            config=CollectorConfig(True, 60, values=cfg["config_values"]),
        )
        return CollectorRegistry({r.plugin_id: r}, generation=generation)

    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.plugin_setup.build_collector_registry",
        build,
    )
    yield plugin
    set_collector_registry(None)


async def prepare(client, monkeypatch):
    vc = await client.post(
        "/api/vcenters",
        json={"name": "vc", "host": "vc.example.net", "username": "u", "password": "p"},
    )
    assert vc.status_code == 201
    key = await client.post("/api/plugins/ssh/credentials", json={"name": "test key"})
    assert key.status_code == 200
    assert "private_key" not in key.json()
    connection = await client.post(
        "/api/plugins/ssh/connections",
        json={
            "name": "esxi",
            "host": "esxi.example.net",
            "port": 22,
            "username": "reader",
            "credential_id": key.json()["id"],
        },
    )
    assert connection.status_code == 200
    c = connection.json()
    host_key = asyncssh.generate_private_key("ssh-ed25519")

    async def probe(*args, **kwargs):
        assert kwargs == {"config": None}
        return host_key

    monkeypatch.setattr(asyncssh, "get_server_host_key", probe)
    return vc.json()["id"], key.json(), c


async def approve(client, c):
    root = "/api/plugins/ssh/connections/" + c["id"]
    probe = await client.post(root + "/host-key")
    assert probe.status_code == 200
    p = probe.json()
    response = await client.post(
        root + "/approve",
        json={"fingerprint": p["candidate_fingerprint"], "revision": p["revision"]},
    )
    assert response.status_code == 200
    return response.json()


async def draft(client, vc_id, c):
    body = {"targets": [{"vcenter_id": vc_id, "ssh_connection_id": c["id"]}]}
    response = await client.put(
        "/api/plugins/collectors/example.setup/draft", json={"config_values": body}
    )
    assert response.status_code == 200
    return response.json()


async def test_management_gate(client):
    for path in [
        "/api/plugins/ssh/credentials",
        "/api/plugins/ssh/connections",
        "/api/plugins/collectors/example.setup/configuration",
    ]:
        assert (await client.get(path)).status_code == 404


async def test_key_requires_encryption_and_rejects_invalid_key(
    client, setup_enabled, monkeypatch
):
    monkeypatch.delenv("VEA_SECRET_KEY")
    get_settings.cache_clear()
    bind_settings(get_settings())
    response = await client.post("/api/plugins/ssh/credentials", json={"name": "key"})
    assert response.status_code == 422
    monkeypatch.setenv("VEA_SECRET_KEY", "setup-test-encryption-key")
    get_settings.cache_clear()
    bind_settings(get_settings())
    response = await client.post(
        "/api/plugins/ssh/credentials",
        json={"name": "key", "private_key": "SECRET-invalid-key"},
    )
    assert response.status_code == 422
    assert "SECRET-invalid-key" not in response.text
    # FastAPI's default validation response echoes input for an invalid type.
    response = await client.post(
        "/api/plugins/ssh/credentials",
        json={"name": "key", "private_key": ["SECRET-invalid-key"]},
    )
    assert response.status_code == 422
    assert "SECRET-invalid-key" not in response.text


async def test_key_encrypted_no_private_response_and_delete_in_use(
    client, setup_enabled, monkeypatch
):
    vc, key, c = await prepare(client, monkeypatch)
    assert "private" not in (await client.get("/api/plugins/ssh/credentials")).text
    async with session_scope(settings=get_settings()) as session:
        stored = await session.scalar(text("SELECT private_key FROM ssh_credentials"))
        assert stored.startswith("enc:") and "PRIVATE KEY" not in stored
        decrypted = await session.scalar(select(SSHCredential.private_key))
        assert "PRIVATE KEY" in decrypted
        parsed = asyncssh.import_private_key(decrypted)
        assert parsed.get_algorithm() == "ssh-rsa"
    assert (
        await client.delete("/api/plugins/ssh/credentials/" + key["id"])
    ).status_code == 409


async def test_host_key_revision_approval_and_reapproval(
    client, setup_enabled, monkeypatch
):
    vc, key, c = await prepare(client, monkeypatch)
    root = "/api/plugins/ssh/connections/" + c["id"]
    first = (await client.post(root + "/host-key")).json()
    assert not first["approved"]
    await client.post(root + "/host-key")
    assert (
        await client.post(
            root + "/approve",
            json={
                "fingerprint": first["candidate_fingerprint"],
                "revision": first["revision"],
            },
        )
    ).status_code == 409
    await approve(client, c)
    changed = await client.put(
        root,
        json={
            "name": "esxi",
            "host": "other.example.net",
            "username": "reader",
            "credential_id": key["id"],
        },
    )
    assert changed.status_code == 200 and not changed.json()["approved"]


async def test_draft_testing_and_atomic_apply(client, setup_enabled, monkeypatch):
    vc, key, c = await prepare(client, monkeypatch)
    d = await draft(client, vc, c)
    base = "/api/plugins/collectors/example.setup/draft"
    assert get_collector_registry().get("example.setup").status == "disabled"
    assert (
        await client.post(base + "/actions/test", json={"revision": d["revision"]})
    ).status_code == 422
    await approve(client, c)
    assert (
        await client.post(base + "/apply", json={"revision": d["revision"]})
    ).status_code == 422
    result = await client.post(base + "/actions/test", json={"revision": d["revision"]})
    assert result.status_code == 200 and result.json()["ok"]
    assert result.json()["samples"] == [{"value": 42}]
    assert (
        await client.post(base + "/apply", json={"revision": d["revision"]})
    ).status_code == 200
    assert get_collector_registry().get("example.setup").status == "enabled"
    async with session_scope(settings=get_settings()) as session:
        applied = await session.get(CollectorPluginSetting, "example.setup")
        assert applied.configuration_managed and applied.enabled
        assert "private_key_file" not in json_dumps(applied.config_values)
    croot = "/api/plugins/ssh/connections/" + c["id"]
    edit = await client.put(
        croot,
        json={
            "name": "different",
            "host": "other.example.net",
            "username": "reader",
            "credential_id": key["id"],
        },
    )
    assert edit.status_code == 409
    new = await client.put(
        "/api/plugins/collectors/example.setup/draft",
        json={"config_values": {"targets": []}, "revision": d["revision"]},
    )
    assert new.json()["tests"] == {}
    assert get_collector_registry().get("example.setup").config.values["targets"]
    # Restart reads only applied settings, even after an unfinished draft changes.
    from vcenter_event_assistant.services.plugin_settings import (
        load_collector_db_overrides,
    )

    async with session_scope(settings=get_settings()) as session:
        restored = (await load_collector_db_overrides(session))["example.setup"]
        assert restored["replace_config"] and restored["config_values"]["targets"]


def json_dumps(value):
    import json

    return json.dumps(value)


async def test_test_invalidated_by_reference_revision(
    client, setup_enabled, monkeypatch
):
    vc, key, c = await prepare(client, monkeypatch)
    c = await approve(client, c)
    d = await draft(client, vc, c)
    base = "/api/plugins/collectors/example.setup/draft"
    await client.post(base + "/actions/test", json={"revision": d["revision"]})
    await client.post("/api/plugins/ssh/connections/" + c["id"] + "/host-key")
    assert (
        await client.post(base + "/apply", json={"revision": d["revision"]})
    ).status_code == 422


async def test_failed_candidate_keeps_database_and_active_registry(
    client, setup_enabled, monkeypatch
):
    vc, key, c = await prepare(client, monkeypatch)
    await approve(client, c)
    d = await draft(client, vc, c)
    base = "/api/plugins/collectors/example.setup/draft"
    await client.post(base + "/actions/test", json={"revision": d["revision"]})
    setup_enabled.fail_start = True
    assert (
        await client.post(base + "/apply", json={"revision": d["revision"]})
    ).status_code == 422
    assert get_collector_registry().get("example.setup").status == "disabled"
    async with session_scope(settings=get_settings()) as session:
        assert await session.get(CollectorPluginSetting, "example.setup") is None


async def test_secret_file_cleanup_on_error_and_mode(
    client, setup_enabled, monkeypatch
):
    from pathlib import Path
    import stat

    vc, key, c = await prepare(client, monkeypatch)
    await approve(client, c)
    d = await draft(client, vc, c)
    file_path = None
    with pytest.raises(RuntimeError):
        async with materialize_ssh(
            get_settings(), d["config_values"], SCHEMA, UUID(vc)
        ) as resolved:
            file_path = Path(resolved["targets"][0]["private_key_file"])
            assert stat.S_IMODE(file_path.stat().st_mode) == 0o400
            assert file_path.read_text().startswith("-----BEGIN OPENSSH PRIVATE KEY")
            raise RuntimeError("test failure")
    assert not file_path.exists()


def test_unsupported_definition_does_not_break_manifest():
    from vcenter_event_assistant.services.plugin_configuration import schema_error

    assert schema_error(
        {"type": "object", "properties": {"a": {"$ref": "https://example.net/schema"}}}
    )
    assert schema_error({"type": "object", "additionalProperties": {"type": "string"}})


async def test_database_failure_keeps_existing_configuration(
    client, setup_enabled, monkeypatch
):
    from sqlalchemy.ext.asyncio import AsyncSession

    vc, key, c = await prepare(client, monkeypatch)
    await approve(client, c)
    d = await draft(client, vc, c)
    base = "/api/plugins/collectors/example.setup/draft"
    await client.post(base + "/actions/test", json={"revision": d["revision"]})
    original = AsyncSession.commit

    async def fail_commit(self):
        if any(isinstance(row, CollectorPluginSetting) for row in self.new):
            raise RuntimeError("DB unavailable")
        await original(self)

    monkeypatch.setattr(AsyncSession, "commit", fail_commit)
    assert (
        await client.post(base + "/apply", json={"revision": d["revision"]})
    ).status_code == 500
    assert get_collector_registry().get("example.setup").status == "disabled"
    async with session_scope(settings=get_settings()) as session:
        assert await session.get(CollectorPluginSetting, "example.setup") is None


async def test_empty_draft_replaces_toml_instead_of_restoring_old_fields(setup_enabled):
    from vcenter_event_assistant.plugins.config import (
        apply_collector_database_overrides,
    )

    assert (
        apply_collector_database_overrides(
            {"config": {"old": "old"}}, {"replace_config": True, "config_values": {}}
        )["config"]
        == {}
    )


async def test_ssh_ip_validation_accepts_appliance_networks_but_not_metadata():
    from fastapi import HTTPException
    from vcenter_event_assistant.api.routes.plugin_setup import validate_host

    assert validate_host("192.168.10.20", get_settings()) == "192.168.10.20"
    for host in ["127.0.0.1", "169.254.169.254", "::1", "0.0.0.0"]:
        with pytest.raises(HTTPException):
            validate_host(host, get_settings())


async def test_uploaded_key_public_download_and_unused_delete(client, setup_enabled):
    key = asyncssh.generate_private_key("ssh-ed25519")
    private = key.export_private_key().decode()
    response = await client.post(
        "/api/plugins/ssh/credentials",
        json={"name": "uploaded", "private_key": private},
    )
    assert response.status_code == 200 and private not in response.text
    identifier = response.json()["id"]
    public = await client.get(
        "/api/plugins/ssh/credentials/" + identifier + "/public-key"
    )
    assert public.json()["public_key"] == key.export_public_key().decode()
    assert (
        await client.delete("/api/plugins/ssh/credentials/" + identifier)
    ).status_code == 200
    assert (
        await client.get("/api/plugins/ssh/credentials/" + identifier + "/public-key")
    ).status_code == 404


async def test_schema_validation_and_stale_draft_revision(client, setup_enabled):
    base = "/api/plugins/collectors/example.setup/draft"
    saved = await client.put(base, json={"config_values": {"targets": []}})
    assert (await client.post(base + "/validate")).status_code == 422
    changed = await client.put(
        base, json={"config_values": {}, "revision": saved.json()["revision"]}
    )
    assert changed.status_code == 200
    assert (
        await client.put(
            base, json={"config_values": {}, "revision": saved.json()["revision"]}
        )
    ).status_code == 409


@pytest.mark.parametrize("connection_value", [None, ""])
async def test_setup_rejects_unselected_ssh_connection_before_worker(
    client, setup_enabled, monkeypatch, connection_value
):
    vc, key, c = await prepare(client, monkeypatch)
    values = {"targets": [{"vcenter_id": vc}]}
    if connection_value is not None:
        values["targets"][0]["ssh_connection_id"] = connection_value
    base = "/api/plugins/collectors/example.setup/draft"
    d = (await client.put(base, json={"config_values": values})).json()
    response = await client.post(
        base + "/actions/test", json={"revision": d["revision"]}
    )
    assert response.status_code == 422
    assert "SSH接続先を選択" in response.json()["detail"]
    assert (await client.post(base + "/validate")).status_code == 422
    async with session_scope(settings=get_settings()) as session:
        assert await session.get(CollectorPluginSetting, "example.setup") is None


async def test_remote_log_schema_resolves_connection_into_worker_context(
    client, setup_enabled, monkeypatch
):
    from pathlib import Path
    from vea_remote_log_collector import RemoteLogCollector
    from vcenter_event_assistant.plugins.wire import context_to_json
    from vcenter_event_assistant.services.plugin_configuration import validate_values

    schema = RemoteLogCollector.manifest.configuration_schema
    setup_enabled.manifest = replace(
        setup_enabled.manifest, configuration_schema=schema
    )
    vc, key, c = await prepare(client, monkeypatch)
    await approve(client, c)
    source = {
        "id": "source-1",
        "vcenter_id": vc,
        "product": "esxi",
        "inventory_host": c["host"],
        "ssh_connection_id": c["id"],
    }
    with pytest.raises(ValueError):
        validate_values({"sources": [{**source, "ssh_connection_id": ""}]}, schema)

    paths = []

    async def inspect_setup(context, action):
        # Inspect exactly the payload used by the remote worker transport.
        resolved = context_to_json(context)["config"]["sources"][0]
        assert resolved["host"] == c["host"]
        assert resolved["port"] == c["port"]
        assert resolved["username"] == c["username"]
        for field in ("private_key_file", "known_hosts_file"):
            path = Path(resolved[field])
            assert path.is_file()
            paths.append(path)
        return SetupResult((SetupCheck("ssh", "SSH接続情報", True),))

    monkeypatch.setattr(setup_enabled, "setup", inspect_setup)
    base = "/api/plugins/collectors/example.setup/draft"
    d = (await client.put(base, json={"config_values": {"sources": [source]}})).json()
    result = await client.post(base + "/actions/test", json={"revision": d["revision"]})
    assert result.status_code == 200 and result.json()["ok"]
    assert paths and all(not path.exists() for path in paths)
    saved = (
        await client.get("/api/plugins/collectors/example.setup/configuration")
    ).json()
    assert saved["draft"]["config_values"] == {"sources": [source]}


async def test_legacy_external_ssh_files_do_not_require_managed_reference():
    from vea_remote_log_collector import RemoteLogCollector

    legacy = {
        "sources": [
            {
                "id": "legacy-source",
                "vcenter_id": "unused",
                "product": "esxi",
                "host": "esxi.example.net",
                "username": "reader",
                "private_key_file": "/mounted/key",
                "known_hosts_file": "/mounted/known_hosts",
            }
        ]
    }
    async with materialize_ssh(
        get_settings(), legacy, RemoteLogCollector.manifest.configuration_schema
    ) as resolved:
        assert resolved == legacy


async def test_secret_files_removed_after_timeout(client, setup_enabled, monkeypatch):
    import asyncio
    from pathlib import Path

    vc, key, c = await prepare(client, monkeypatch)
    await approve(client, c)
    d = await draft(client, vc, c)
    path = None
    with pytest.raises(TimeoutError):
        async with materialize_ssh(
            get_settings(), d["config_values"], SCHEMA, UUID(vc)
        ) as resolved:
            path = Path(resolved["targets"][0]["private_key_file"])
            async with asyncio.timeout(0.01):
                await asyncio.Event().wait()
    assert path is not None and not path.exists()


def test_startup_cleans_abandoned_files_without_touching_other_processes(
    tmp_path, monkeypatch
):
    import os
    from vcenter_event_assistant.services.ssh_management import cleanup_stale_ssh_files

    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    current = tmp_path / f"vea-ssh-{os.getpid()}"
    abandoned = tmp_path / "vea-ssh-99999999"
    live = tmp_path / "vea-ssh-99999998"
    for path in (current, abandoned, live):
        path.mkdir()
        (path / "secret.key").write_text("test private material")

    def process_probe(pid, signal):
        if pid == 99999999:
            raise ProcessLookupError()

    monkeypatch.setattr(os, "kill", process_probe)
    cleanup_stale_ssh_files()
    assert not current.exists() and not abandoned.exists()
    assert (live / "secret.key").exists()
