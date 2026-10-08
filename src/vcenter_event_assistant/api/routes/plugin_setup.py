"""Common declarative onboarding and managed SSH APIs."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.auth_deps import RequireAdmin
from vcenter_event_assistant.api.deps import get_app_settings, get_session
from vcenter_event_assistant.api.routes.plugins import management_gate
from vcenter_event_assistant.db.models import (
    CollectorPluginSetting,
    PluginConfigurationDraft,
    SSHConnection,
    SSHCredential,
    VCenter,
)
from vcenter_event_assistant.plugins.config import collector_environment_prefix
from vcenter_event_assistant.plugins.registry import (
    get_collector_registry,
    build_collector_registry,
    start_collector_registry,
    shutdown_collector_registry,
    activate_collector_registry,
)
from vcenter_event_assistant.plugins.reload import _reload_lock
from vcenter_event_assistant.services.plugin_configuration import (
    run_setup,
    schema_error,
    validate_values,
    validate_targets,
)
from vcenter_event_assistant.services.plugin_settings import load_collector_db_overrides
from vcenter_event_assistant.services.ssh_management import (
    connection_read,
    fingerprint,
    reference_digest,
)
from vcenter_event_assistant.settings import Settings


async def mutation_gate():
    async with _reload_lock:
        yield


class SafeSetupRoute(APIRoute):
    """Validation errors must never echo uploaded private material."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse(
                    status_code=422,
                    content={"detail": "入力の形式を確認してください。"},
                )

        return safe_handler


router = APIRouter(
    prefix="/plugins",
    tags=["plugin setup"],
    # 無効時に存在を伏せる 404 gate を先に評価し、そのうえで admin を要求する
    # （ログイン確認より先に gate を評価するマウントは main.create_app を参照）。
    dependencies=[Depends(management_gate), RequireAdmin],
    route_class=SafeSetupRoute,
)


def registration(plugin_id):
    r = get_collector_registry().get(plugin_id)
    if r is None or r.plugin is None:
        raise HTTPException(404, "プラグインが見つかりません。")
    return r


def definition(r):
    manifest = r.plugin.manifest
    prefix = collector_environment_prefix(manifest.id)
    return {
        "schema": manifest.configuration_schema,
        "unavailable_reason": schema_error(manifest.configuration_schema),
        "actions": [
            {"id": a.id, "title": a.title, "required_for_enable": a.required_for_enable}
            for a in manifest.setup_actions
        ],
        "env_locked_fields": [
            key[len(prefix) :].lower() for key in os.environ if key.startswith(prefix)
        ],
    }


def draft_read(d):
    return {"config_values": d.config_values, "revision": d.revision, "tests": d.tests}


class DraftInput(BaseModel):
    config_values: dict = Field(default_factory=dict)
    revision: int | None = None


class RevisionInput(BaseModel):
    revision: int


class KeyInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    private_key: SecretStr | None = None


class ConnectionInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    host: str = Field(min_length=1, max_length=512)
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=512)
    credential_id: UUID


class ApprovalInput(BaseModel):
    fingerprint: str
    revision: int


async def get_draft(session, plugin_id):
    d = await session.get(PluginConfigurationDraft, plugin_id)
    if d is None:
        d = PluginConfigurationDraft(
            plugin_id=plugin_id, config_values={}, tests={}, revision=1
        )
        session.add(d)
        await session.flush()
    return d


def check_revision(d, revision):
    if revision != d.revision:
        raise HTTPException(409, "設定が更新されています。画面を読み直してください。")


def input_error(exc):
    raise HTTPException(422, str(exc)) from None


@router.get("/collectors/{plugin_id}/configuration")
async def get_configuration(
    plugin_id: str, session: AsyncSession = Depends(get_session)
):
    r = registration(plugin_id)
    d = await session.get(PluginConfigurationDraft, plugin_id)
    return {**definition(r), "draft": draft_read(d) if d else None}


@router.put("/collectors/{plugin_id}/draft", dependencies=[Depends(mutation_gate)])
async def put_draft(
    plugin_id: str, body: DraftInput, session: AsyncSession = Depends(get_session)
):
    r = registration(plugin_id)
    if schema_error(r.plugin.manifest.configuration_schema):
        raise HTTPException(422, schema_error(r.plugin.manifest.configuration_schema))
    if len(json.dumps(body.config_values).encode()) > 256 * 1024:
        raise HTTPException(413, "設定のサイズが上限を超えています。")
    d = await get_draft(session, plugin_id)
    if body.revision is not None:
        check_revision(d, body.revision)
    if d.config_values != body.config_values:
        d.config_values = body.config_values
        d.revision += 1
        d.tests = {}
    await session.flush()
    return draft_read(d)


@router.post(
    "/collectors/{plugin_id}/draft/import", dependencies=[Depends(mutation_gate)]
)
async def import_configuration(
    plugin_id: str, session: AsyncSession = Depends(get_session)
):
    r = registration(plugin_id)
    values = copy.deepcopy(dict(r.config.values))

    # Only declaration-marked SSH objects lose legacy path references. No key files are imported.
    def strip(value, schema):
        if isinstance(value, dict):
            if schema.get("x-vea-ssh-connection"):
                for key, child in schema.get("properties", {}).items():
                    if child.get("x-vea-widget") == "esxi-host" and value.get("host"):
                        value[key] = value["host"]
                for name in (
                    "private_key_file",
                    "known_hosts_file",
                    "host",
                    "port",
                    "username",
                ):
                    value.pop(name, None)
            for name, child in schema.get("properties", {}).items():
                if name in value:
                    strip(value[name], child)
        elif isinstance(value, list):
            for item in value:
                strip(item, schema.get("items", {}))

    if schema_error(r.plugin.manifest.configuration_schema):
        raise HTTPException(422, "設定の移行に対応していません。")
    strip(values, r.plugin.manifest.configuration_schema)
    d = await get_draft(session, plugin_id)
    d.config_values, d.tests, d.revision = values, {}, d.revision + 1
    return draft_read(d)


@router.post("/collectors/{plugin_id}/draft/validate")
async def validate_draft(plugin_id: str, session: AsyncSession = Depends(get_session)):
    r = registration(plugin_id)
    d = await session.get(PluginConfigurationDraft, plugin_id)
    if not d:
        raise HTTPException(422, "下書きを保存してください。")
    try:
        validate_values(d.config_values, r.plugin.manifest.configuration_schema)
        await validate_targets(
            session, d.config_values, r.plugin.manifest.configuration_schema
        )
        await reference_digest(
            session, d.config_values, r.plugin.manifest.configuration_schema
        )
    except ValueError as exc:
        input_error(exc)
    return {"ok": True}


@router.post(
    "/collectors/{plugin_id}/draft/actions/{action}",
    dependencies=[Depends(mutation_gate)],
)
async def execute_action(
    plugin_id: str,
    action: str,
    body: RevisionInput,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
):
    r = registration(plugin_id)
    if action not in {a.id for a in r.plugin.manifest.setup_actions}:
        raise HTTPException(404, "この操作は提供されていません。")
    d = await session.get(PluginConfigurationDraft, plugin_id)
    if not d:
        raise HTTPException(422, "下書きを保存してください。")
    check_revision(d, body.revision)
    try:
        digest = await reference_digest(
            session, d.config_values, r.plugin.manifest.configuration_schema
        )
        started = time.monotonic()
        result = await run_setup(settings, r, copy.deepcopy(d.config_values), action)
    except ValueError as exc:
        input_error(exc)
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    ok = bool(result["checks"]) and all(c["ok"] for c in result["checks"])
    d.tests = {
        **d.tests,
        action: {"ok": ok, "digest": digest, "version": r.plugin.manifest.version},
    }
    await session.flush()
    return {**result, "ok": ok, "draft": draft_read(d)}


@router.post(
    "/collectors/{plugin_id}/draft/apply", dependencies=[Depends(mutation_gate)]
)
async def apply_configuration(
    plugin_id: str,
    body: RevisionInput,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
):
    from vcenter_event_assistant.jobs.scheduler import reconcile_collector_jobs

    r = registration(plugin_id)
    d = await session.get(PluginConfigurationDraft, plugin_id)
    if not d:
        raise HTTPException(422, "下書きを保存してください。")
    check_revision(d, body.revision)
    if definition(r)["env_locked_fields"]:
        raise HTTPException(
            409, "環境変数で固定されています。環境変数の設定を確認してください。"
        )
    try:
        validate_values(d.config_values, r.plugin.manifest.configuration_schema)
        await validate_targets(
            session, d.config_values, r.plugin.manifest.configuration_schema
        )
        digest = await reference_digest(
            session, d.config_values, r.plugin.manifest.configuration_schema
        )
    except ValueError as exc:
        input_error(exc)
    for a in r.plugin.manifest.setup_actions:
        test = d.tests.get(a.id, {})
        if a.required_for_enable and (
            not test.get("ok")
            or test.get("digest") != digest
            or test.get("version") != r.plugin.manifest.version
        ):
            raise HTTPException(422, "現在の設定で接続テストを完了してください。")
    overrides = await load_collector_db_overrides(session)
    overrides[plugin_id] = {
        **overrides.get(plugin_id, {}),
        "enabled": True,
        "config_values": copy.deepcopy(d.config_values),
        "replace_config": True,
    }
    previous = get_collector_registry()
    candidate = await asyncio.to_thread(
        build_collector_registry,
        settings,
        generation=previous.generation + 1,
        db_overrides=overrides,
    )
    candidate = await start_collector_registry(candidate)
    failures = [
        x
        for x in candidate.registrations.values()
        if x.status == "failed"
        and (
            x.plugin_id == plugin_id
            or (
                previous.get(x.plugin_id)
                and previous.get(x.plugin_id).status == "enabled"
            )
        )
    ]
    if failures or candidate.get(plugin_id).status != "enabled":
        await shutdown_collector_registry(candidate)
        raise HTTPException(
            422, "設定を適用できませんでした。既存の収集設定は維持されています。"
        )
    row = await session.get(CollectorPluginSetting, plugin_id)
    if not row:
        row = CollectorPluginSetting(plugin_id=plugin_id)
        session.add(row)
    row.config_values, row.enabled = copy.deepcopy(d.config_values), True
    row.configuration_managed = True
    scheduler = getattr(request.app.state, "scheduler", None)
    try:
        if scheduler:
            reconcile_collector_jobs(scheduler, settings, candidate)
        await session.commit()
    except Exception:
        if scheduler:
            reconcile_collector_jobs(scheduler, settings, previous)
        await shutdown_collector_registry(candidate)
        raise HTTPException(
            500, "設定を保存できませんでした。既存の収集設定は維持されています。"
        ) from None
    activate_collector_registry(candidate)
    await shutdown_collector_registry(previous)
    return {"ok": True, "generation": candidate.generation}


@router.get("/ssh/credentials")
async def list_credentials(session: AsyncSession = Depends(get_session)):
    # Selecting only public metadata avoids decrypting private keys for a list.
    rows = (
        await session.execute(
            select(SSHCredential.id, SSHCredential.name, SSHCredential.public_key)
        )
    ).all()
    return [{"id": str(i), "name": name, "public_key": pub} for i, name, pub in rows]


@router.post("/ssh/credentials", dependencies=[Depends(mutation_gate)])
async def create_credential(
    body: KeyInput,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
):
    import asyncssh

    if not settings.vea_secret_key:
        raise HTTPException(422, "管理者にVEA_SECRET_KEYの設定を依頼してください。")
    try:
        if body.private_key is None:
            key = await asyncio.to_thread(
                asyncssh.generate_private_key, "ssh-rsa", key_size=3072
            )
        else:
            value = body.private_key.get_secret_value()
            if len(value.encode()) > 32768:
                raise ValueError()
            key = asyncssh.import_private_key(value)
        private = key.export_private_key("openssh").decode()
        public = key.export_public_key("openssh").decode()
    except Exception:
        raise HTTPException(
            422, "秘密鍵を読み込めません。パスフレーズ不要のSSH秘密鍵を選んでください。"
        ) from None
    row = SSHCredential(name=body.name, private_key=private, public_key=public)
    session.add(row)
    await session.flush()
    return {"id": str(row.id), "name": row.name, "public_key": row.public_key}


@router.get("/ssh/credentials/{identifier}/public-key")
async def public_key(identifier: UUID, session: AsyncSession = Depends(get_session)):
    row = await session.execute(
        select(SSHCredential.public_key).where(SSHCredential.id == identifier)
    )
    value = row.scalar_one_or_none()
    if value is None:
        raise HTTPException(404, "SSH鍵が見つかりません。")
    return {"public_key": value}


@router.delete("/ssh/credentials/{identifier}", dependencies=[Depends(mutation_gate)])
async def delete_credential(
    identifier: UUID, session: AsyncSession = Depends(get_session)
):
    if await session.scalar(
        select(SSHConnection.id)
        .where(SSHConnection.credential_id == identifier)
        .limit(1)
    ):
        raise HTTPException(409, "接続先で使用中の鍵は削除できません。")
    if not await session.scalar(
        select(SSHCredential.id).where(SSHCredential.id == identifier)
    ):
        raise HTTPException(404, "SSH鍵が見つかりません。")
    await session.execute(delete(SSHCredential).where(SSHCredential.id == identifier))
    return {"ok": True}


@router.get("/ssh/connections")
async def list_connections(session: AsyncSession = Depends(get_session)):
    return [
        connection_read(row)
        for row in (await session.scalars(select(SSHConnection))).all()
    ]


def validate_host(host, settings):
    import ipaddress
    from vcenter_event_assistant.services.vcenter_host_validation import (
        validate_vcenter_host,
    )

    # Explicit operator-managed SSH endpoints may be RFC1918 appliance IPs.
    # Loopback, metadata/link-local, multicast and unspecified addresses remain blocked.
    normalized = host.strip()
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        try:
            return validate_vcenter_host(
                normalized,
                resolve_dns=False,
                allowed_suffixes=settings.vcenter_allowed_host_suffix_list or None,
            )
        except ValueError:
            raise HTTPException(
                422, "ホスト名またはIPアドレスを確認してください。"
            ) from None
    if (
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    ):
        raise HTTPException(422, "このIPアドレスにはSSH接続できません。")
    return str(address)


@router.post("/ssh/connections", dependencies=[Depends(mutation_gate)])
async def create_connection(
    body: ConnectionInput,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
):
    if not await session.scalar(
        select(SSHCredential.id).where(SSHCredential.id == body.credential_id)
    ):
        raise HTTPException(422, "SSH鍵を選択してください。")
    row = SSHConnection(**body.model_dump(), revision=1)
    row.host = validate_host(body.host, settings)
    session.add(row)
    await session.flush()
    return connection_read(row)


async def get_connection(session, identifier):
    row = await session.get(SSHConnection, identifier)
    if not row:
        raise HTTPException(404, "接続先が見つかりません。")
    return row


async def ensure_not_active(session, identifier):
    from vcenter_event_assistant.services.ssh_management import ssh_objects

    for r in get_collector_registry().enabled():
        if r.plugin and any(
            i == str(identifier)
            for _, i in ssh_objects(
                r.config.values, r.plugin.manifest.configuration_schema
            )
        ):
            raise HTTPException(
                409,
                "収集中の接続先です。新しい接続先を作成して、テスト後に設定を適用してください。",
            )
    for config in (
        await session.scalars(
            select(CollectorPluginSetting.config_values).where(
                CollectorPluginSetting.enabled.is_(True)
            )
        )
    ).all():
        if str(identifier) in json.dumps(config):
            raise HTTPException(
                409,
                "保存済みの収集設定で使用中です。別の接続先として登録してください。",
            )


@router.put("/ssh/connections/{identifier}", dependencies=[Depends(mutation_gate)])
async def update_connection(
    identifier: UUID,
    body: ConnectionInput,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
):
    await ensure_not_active(session, identifier)
    row = await get_connection(session, identifier)
    if not await session.scalar(
        select(SSHCredential.id).where(SSHCredential.id == body.credential_id)
    ):
        raise HTTPException(422, "SSH鍵が見つかりません。")
    host = validate_host(body.host, settings)
    if (row.host, row.port) != (host, body.port):
        row.candidate_key = row.approved_key = None
    for key, value in body.model_dump().items():
        setattr(row, key, host if key == "host" else value)
    row.revision += 1
    return connection_read(row)


@router.post(
    "/ssh/connections/{identifier}/host-key", dependencies=[Depends(mutation_gate)]
)
async def probe_host_key(
    identifier: UUID, session: AsyncSession = Depends(get_session)
):
    import asyncssh

    row = await get_connection(session, identifier)
    try:
        async with asyncio.timeout(10):
            key = await asyncssh.get_server_host_key(row.host, row.port, config=None)
        if key is None:
            raise ValueError()
    except Exception:
        raise HTTPException(
            422,
            "ホスト鍵を取得できません。SSHの有効化・接続先・ポートを確認してください。",
        ) from None
    row.candidate_key = key.export_public_key("openssh").decode()
    row.revision += 1
    return connection_read(row)


@router.post(
    "/ssh/connections/{identifier}/approve", dependencies=[Depends(mutation_gate)]
)
async def approve_host_key(
    identifier: UUID, body: ApprovalInput, session: AsyncSession = Depends(get_session)
):
    row = await get_connection(session, identifier)
    if (
        row.revision != body.revision
        or not row.candidate_key
        or fingerprint(row.candidate_key) != body.fingerprint
    ):
        raise HTTPException(409, "ホスト鍵の取得をやり直してください。")
    if row.approved_key != row.candidate_key:
        await ensure_not_active(session, identifier)
    row.approved_key = row.candidate_key
    row.revision += 1
    return connection_read(row)


@router.get("/vcenters/{identifier}/hosts")
async def list_hosts(
    identifier: UUID,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
):
    from vcenter_event_assistant.collectors.connection import (
        connect_vcenter,
        disconnect,
    )
    from vcenter_event_assistant_plugin_api.vmware import container_view

    vc = await session.get(VCenter, identifier)
    if not vc or not vc.is_enabled:
        raise HTTPException(422, "有効なvCenterを選択してください。")
    if settings.mock_mode:
        return [
            {"id": "mock-esxi", "name": "mock-esxi.local", "host": "mock-esxi.local"}
        ]

    def fetch():
        si = connect_vcenter(
            host=vc.host,
            protocol=vc.protocol,
            port=vc.port,
            username=vc.username,
            password=vc.password,
            proxy_url=settings.vcenter_http_proxy,
            verify_ssl=vc.verify_ssl,
            ca_bundle_path=settings.vcenter_ca_bundle,
        )
        try:
            with container_view(si, ["HostSystem"]) as hosts:
                return [
                    {"id": str(h._moId), "name": str(h.name), "host": str(h.name)}
                    for h in hosts
                ]
        finally:
            disconnect(si)

    try:
        return await asyncio.to_thread(fetch)
    except Exception:
        raise HTTPException(
            422,
            "ESXi一覧を取得できません。vCenterの接続設定・参照権限を確認するか、ホスト名を手入力してください。",
        ) from None
