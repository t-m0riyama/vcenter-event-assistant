"""診断設定 API の権限、SSH の用途、楽観ロックと監査を検証する。"""

import subprocess
import sys
from datetime import datetime, timezone
from uuid import uuid4

import asyncssh
import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from vcenter_event_assistant.api.routes import ssh_setup
from vcenter_event_assistant.api.schemas.diagnostics import CommandCatalog
from vcenter_event_assistant.db.models import (
    DiagnosticTarget,
    SSHConnection,
    SSHCredential,
    VCenter,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.main import _rate_limit_spec, create_app
from vcenter_event_assistant.plugins.registry import CollectorRegistry
from vcenter_event_assistant.settings import get_settings
from vcenter_event_assistant.settings_binding import bind_settings

ROOT = "/api/diagnostics"
PLUGIN = "/api/plugins"
COMMAND = {
    "product": "esxi",
    "title": "NIC の統計",
    "description": "",
    "template": "esxcli network nic stats get -n {{nic}}",
    "param_definitions": [{"name": "nic", "type": "vmnic"}],
}


@pytest.fixture
def diagnostics_enabled(monkeypatch):
    monkeypatch.setenv("VEA_DIAGNOSTICS_ENABLED", "true")
    monkeypatch.setenv("VEA_SECRET_KEY", "diagnostics-test-key")
    get_settings.cache_clear()
    bind_settings(get_settings())


async def create_key(client, prefix, name="SSH 鍵"):
    key = (
        asyncssh.generate_private_key("ssh-ed25519")
        .export_private_key("openssh")
        .decode()
    )
    response = await client.post(
        f"{prefix}/ssh/credentials", json={"name": name, "private_key": key}
    )
    assert response.status_code == 200, response.text
    assert key not in response.text
    return response.json(), key


def connection_body(credential_id):
    return {
        "name": "管理 SSH",
        "host": "ssh.example.net",
        "username": "reader",
        "credential_id": credential_id,
    }


async def create_connection(client, prefix, credential_id):
    response = await client.post(
        f"{prefix}/ssh/connections", json=connection_body(credential_id)
    )
    assert response.status_code == 200, response.text
    return response.json()


async def create_vcenter():
    async with session_scope() as session:
        row = VCenter(
            name="診断 vCenter",
            host="vc.example.net",
            username="reader",
            password="test-password",
        )
        session.add(row)
        await session.flush()
        return row.id


def test_diagnostics_refuses_to_start_without_auth(monkeypatch):
    monkeypatch.setenv("VEA_DIAGNOSTICS_ENABLED", "true")
    monkeypatch.setenv("VEA_AUTH_ENABLED", "false")
    get_settings.cache_clear()
    with pytest.raises(
        ValidationError, match="VEA_DIAGNOSTICS_ENABLED=true には VEA_AUTH_ENABLED=true"
    ):
        create_app()


async def test_diagnostics_config_defaults_to_disabled(viewer_client):
    assert (await viewer_client.get("/api/config")).json()[
        "diagnostics_enabled"
    ] is False


async def test_diagnostics_is_independent_of_plugin_gate(
    diagnostics_enabled, viewer_client, client, anon_client
):
    assert (await viewer_client.get("/api/config")).json()[
        "diagnostics_enabled"
    ] is True
    assert (await viewer_client.get(ROOT + "/commands")).status_code == 403
    assert (await anon_client.get(ROOT + "/commands")).status_code == 401
    assert (await client.get(ROOT + "/commands")).status_code == 200
    assert (await client.get(PLUGIN + "/ssh/credentials")).status_code == 404


@pytest.mark.parametrize("prefix", [ROOT, PLUGIN])
async def test_diagnostics_ssh_cross_purpose_isolation(
    diagnostics_enabled, client, monkeypatch, prefix
):
    monkeypatch.setenv("VEA_PLUGIN_MANAGEMENT_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "vcenter_event_assistant.api.routes.plugin_setup.get_collector_registry",
        lambda: CollectorRegistry({}),
    )
    other = ROOT if prefix == PLUGIN else PLUGIN
    key, _ = await create_key(client, prefix, "同じ用途")
    other_key, _ = await create_key(client, other, "別用途")
    connection = await create_connection(client, prefix, key["id"])
    other_connection = await create_connection(client, other, other_key["id"])

    assert (await client.get(f"{prefix}/ssh/credentials")).json() == [key]
    assert (await client.get(f"{prefix}/ssh/connections")).json() == [connection]
    key_path = f"{prefix}/ssh/credentials/{other_key['id']}"
    assert (await client.get(key_path + "/public-key")).status_code == 404
    # 他用途の接続先が鍵を使っていても、鍵の存在を 409 で漏らさない。
    assert (await client.delete(key_path)).status_code == 404
    assert (
        await client.post(
            f"{prefix}/ssh/connections", json=connection_body(other_key["id"])
        )
    ).status_code == 422
    assert (
        await client.put(
            f"{prefix}/ssh/connections/{connection['id']}",
            json=connection_body(other_key["id"]),
        )
    ).status_code == 422

    path = f"{prefix}/ssh/connections/{other_connection['id']}"
    assert (await client.put(path, json=connection_body(key["id"]))).status_code == 404
    assert (await client.post(path + "/host-key")).status_code == 404
    assert (
        await client.post(
            path + "/approve", json={"fingerprint": "unused", "revision": 1}
        )
    ).status_code == 404


async def test_diagnostics_ssh_validation_audit_and_probe(
    diagnostics_enabled, client, monkeypatch, caplog
):
    async def resolve(host, port):
        assert (host, port) == ("ssh.example.net", 22)
        return "192.0.2.10"

    async def probe(address, port, *, config):
        assert (address, port, config) == ("192.0.2.10", 22, None)
        return asyncssh.generate_private_key("ssh-ed25519")

    monkeypatch.setattr(ssh_setup, "resolve_ssh_address", resolve)
    monkeypatch.setattr(asyncssh, "get_server_host_key", probe)
    caplog.set_level("INFO", logger="vcenter_event_assistant.audit")

    marker = "PRIVATE-MATERIAL-SHOULD-NOT-APPEAR"
    response = await client.post(
        ROOT + "/ssh/credentials", json={"private_key": marker}
    )
    assert response.status_code == 422
    assert marker not in response.text
    key, private = await create_key(client, ROOT)
    unused, _ = await create_key(client, ROOT, "未使用")
    assert (
        await client.delete(f"{ROOT}/ssh/credentials/{unused['id']}")
    ).status_code == 200
    connection = await create_connection(client, ROOT, key["id"])
    path = f"{ROOT}/ssh/connections/{connection['id']}"
    edited = await client.put(path, json=connection_body(key["id"]))
    assert edited.status_code == 200
    first = (await client.post(path + "/host-key")).json()
    second = (await client.post(path + "/host-key")).json()
    assert (
        await client.post(
            path + "/approve",
            json={
                "fingerprint": first["candidate_fingerprint"],
                "revision": first["revision"],
            },
        )
    ).status_code == 409
    approved = await client.post(
        path + "/approve",
        json={
            "fingerprint": second["candidate_fingerprint"],
            "revision": second["revision"],
        },
    )
    assert approved.status_code == 200 and approved.json()["approved"]
    for event in (
        "credential.created",
        "credential.deleted",
        "connection.created",
        "connection.updated",
        "connection.host_key_probed",
        "connection.host_key_approved",
    ):
        assert f"event=diagnostics.ssh.{event}" in caplog.text
    assert (
        "username=test-admin" in caplog.text
        and "user_id=" in caplog.text
        and "ip=" in caplog.text
    )
    assert marker not in caplog.text and private not in caplog.text
    assert "OPENSSH PRIVATE KEY" not in caplog.text


async def test_diagnostics_ssh_probe_rejects_concurrent_connection_update(
    diagnostics_enabled,
    client,
    monkeypatch,
):
    key, _ = await create_key(client, ROOT)
    connection = await create_connection(client, ROOT, key["id"])
    list_path = f"{ROOT}/ssh/connections"
    path = f"{list_path}/{connection['id']}"
    changed_host = "changed.example.net"

    async def resolve(host, port):
        assert host == connection["host"]
        return "192.0.2.10"

    async def probe(address, port, *, config):
        # 古い接続先のホスト鍵が返る前に、別の要求で接続先を変更する。
        updated = await client.put(
            path, json={**connection_body(key["id"]), "host": changed_host}
        )
        assert updated.status_code == 200, updated.text
        return asyncssh.generate_private_key("ssh-ed25519")

    monkeypatch.setattr(ssh_setup, "resolve_ssh_address", resolve)
    monkeypatch.setattr(asyncssh, "get_server_host_key", probe)

    response = await client.post(path + "/host-key")
    assert response.status_code == 409
    [saved] = (await client.get(list_path)).json()
    assert saved["host"] == changed_host
    assert saved["revision"] == connection["revision"] + 1
    assert saved["candidate_fingerprint"] is None


async def test_diagnostics_hosts_and_probes_share_rate_limit(
    diagnostics_enabled, client, monkeypatch
):
    monkeypatch.setenv("MOCK_MODE", "true")
    get_settings.cache_clear()
    vc_id = await create_vcenter()
    assert (await client.get(f"{ROOT}/vcenters/{vc_id}/hosts")).json() == [
        {"id": "mock-esxi", "name": "mock-esxi.local", "host": "mock-esxi.local"},
    ]
    assert _rate_limit_spec("GET", f"{ROOT}/vcenters/{vc_id}/hosts") == ("probe", 60)
    assert _rate_limit_spec("POST", f"{ROOT}/ssh/connections/{uuid4()}/host-key") == (
        "probe",
        60,
    )


def test_diagnostics_builtin_command_response_includes_string_id():
    builtin = {"id": "esxi.nic-stats", **COMMAND}
    catalog = CommandCatalog.model_validate(
        {"builtin": [builtin], "custom": [], "parameter_types": []}
    )
    assert catalog.model_dump(mode="json")["builtin"] == [builtin]
    with pytest.raises(ValidationError, match="id"):
        CommandCatalog.model_validate(
            {"builtin": [COMMAND], "custom": [], "parameter_types": []}
        )


async def test_diagnostics_command_catalog_and_revision(
    diagnostics_enabled, client, caplog
):
    path = ROOT + "/commands"
    caplog.set_level("INFO", logger="vcenter_event_assistant.audit")
    catalog = (await client.get(path)).json()
    assert len(catalog["builtin"]) == 19
    assert catalog["custom"] == []
    assert catalog["parameter_types"] == ["vmnic", "vmk", "ipv4", "device"]
    response = await client.post(path, json={**COMMAND, "template": "hostname {{Vmk}}"})
    assert response.status_code == 422
    assert response.headers["X-VEA-Error-Code"] == "diagnostic_template_invalid"
    assert response.json()["detail"] == {
        "reason": "undefined_parameter",
        "parameter": "Vmk",
    }

    created = await client.post(path, json=COMMAND)
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["created_by"] == row["updated_by"] == "test-admin"
    assert (await client.get(path)).json()["custom"] == [row]
    path += f"/{row['id']}"
    changed = {**COMMAND, "revision": row["revision"], "title": "NIC"}
    invalid = await client.put(path, json={**changed, "template": r"hostname \{{nic}}"})
    assert invalid.status_code == 422
    assert invalid.headers["X-VEA-Error-Code"] == "diagnostic_template_invalid"
    assert invalid.json()["detail"] == {
        "reason": "backslash_prefix",
        "parameter": "nic",
    }
    updated = await client.put(path, json=changed)
    assert updated.status_code == 200, updated.text
    new = updated.json()
    assert new["revision"] != row["revision"] and new["title"] == "NIC"
    assert (await client.put(path, json=changed)).status_code == 409
    assert (
        await client.delete(path, params={"revision": row["revision"]})
    ).status_code == 409
    assert (
        await client.delete(path, params={"revision": new["revision"]})
    ).status_code == 200
    assert (
        await client.delete(path, params={"revision": new["revision"]})
    ).status_code == 404
    assert (await client.get(ROOT + "/commands")).json()["custom"] == []
    for event in ("created", "updated", "deleted"):
        assert f"event=diagnostics.command.{event}" in caplog.text
    assert "param_definitions=" in caplog.text and COMMAND["template"] in caplog.text


async def test_diagnostics_target_validation_and_revision(
    diagnostics_enabled, client, caplog
):
    caplog.set_level("INFO", logger="vcenter_event_assistant.audit")
    key, _ = await create_key(client, ROOT)
    connection = await create_connection(client, ROOT, key["id"])
    vc_id = await create_vcenter()
    path = ROOT + "/targets"
    body = {
        "product": "esxi",
        "vcenter_id": str(vc_id),
        "host_moid": "host-11",
        "host_name": "診断 ESXi",
        "ssh_connection_id": connection["id"],
    }
    async with session_scope() as session:
        legacy_key = SSHCredential(
            name="収集鍵", private_key="key", public_key="public"
        )
        session.add(legacy_key)
        await session.flush()
        legacy = SSHConnection(
            name="収集先",
            host="ssh.example.net",
            username="reader",
            credential_id=legacy_key.id,
        )
        session.add(legacy)
        await session.flush()
        legacy_id = str(legacy.id)
    assert (
        await client.post(path, json={**body, "ssh_connection_id": legacy_id})
    ).status_code == 422
    assert (
        await client.post(path, json={**body, "host_moid": None})
    ).status_code == 422
    assert (
        await client.post(path, json={**body, "product": "vcenter"})
    ).status_code == 422
    created = await client.post(path, json=body)
    assert created.status_code == 201, created.text
    row = created.json()
    assert (await client.get(path)).json() == [row]
    assert (await client.post(path, json=body)).status_code == 409
    path += f"/{row['id']}"
    changed = {**body, "revision": row["revision"], "host_name": "更新済み"}
    assert (
        await client.put(path, json={**changed, "ssh_connection_id": legacy_id})
    ).status_code == 422
    updated = await client.put(path, json=changed)
    assert updated.status_code == 200, updated.text
    assert (await client.put(path, json=changed)).status_code == 409
    assert (
        await client.delete(path, params={"revision": row["revision"]})
    ).status_code == 409
    assert (
        await client.delete(path, params={"revision": updated.json()["revision"]})
    ).status_code == 200
    for event in ("created", "updated", "deleted"):
        assert f"event=diagnostics.target.{event}" in caplog.text
    assert (
        str(vc_id) in caplog.text
        and connection["id"] in caplog.text
        and "host_moid=host-11" in caplog.text
    )


@pytest.mark.parametrize("incident_db", ["sqlite", "postgres"], indirect=True)
async def test_diagnostics_target_model_constraints(incident_db, diagnostics_enabled):
    vc_id = await create_vcenter()
    async with session_scope() as session:
        key = SSHCredential(
            name="診断鍵", private_key="key", public_key="public", purpose="diagnostics"
        )
        session.add(key)
        await session.flush()
        conn = SSHConnection(
            name="診断先",
            host="ssh.example.net",
            username="reader",
            credential_id=key.id,
            purpose="diagnostics",
        )
        session.add(conn)
        await session.flush()
        conn_id = conn.id
        now = datetime.now(timezone.utc)

        def target(product, moid):
            return DiagnosticTarget(
                vcenter_id=vc_id,
                product=product,
                host_moid=moid,
                host_name="target",
                ssh_connection_id=conn_id,
                created_at=now,
                updated_at=now,
                created_by="admin",
                updated_by="admin",
            )

        session.add_all(
            [
                target("esxi", "host-1"),
                target("esxi", "host-2"),
                target("vcenter", None),
            ]
        )
        await session.flush()
        for product, moid in [
            ("esxi", None),
            ("vcenter", "host-3"),
            ("other", "host-3"),
            ("esxi", "host-1"),
            ("vcenter", None),
        ]:
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    session.add(target(product, moid))
                    await session.flush()

        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await session.execute(
                    delete(SSHConnection).where(SSHConnection.id == conn_id)
                )
        await session.execute(delete(VCenter).where(VCenter.id == vc_id))
        assert list(await session.scalars(select(DiagnosticTarget.id))) == []


def test_diagnostics_audit_logger_reports_at_warning(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
from vcenter_event_assistant.auth.audit import audit
from vcenter_event_assistant.logging_config import configure_logging
from vcenter_event_assistant.settings import get_settings
configure_logging(get_settings())
audit("diagnostics.command.created")
""",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert (
        result.stderr.count(
            "INFO [vcenter_event_assistant.audit] AUDIT event=diagnostics.command.created"
        )
        == 1
    )
