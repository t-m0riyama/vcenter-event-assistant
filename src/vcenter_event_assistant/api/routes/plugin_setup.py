"""Common declarative onboarding and managed SSH APIs."""

from __future__ import annotations

import asyncio
import copy
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.auth_deps import RequireAdmin
from vcenter_event_assistant.api.deps import get_app_settings, get_session
from vcenter_event_assistant.api.routes.setup_common import PluginSetupRoute, list_hosts
from vcenter_event_assistant.api.routes.ssh_setup import ssh_setup_router
from vcenter_event_assistant.db.models import (
    CollectorPluginSetting,
    PluginConfigurationDraft,
)
from vcenter_event_assistant.plugins.registry import (
    get_collector_registry,
    build_collector_registry,
    shutdown_collector_registry,
    activate_collector_registry,
)
from vcenter_event_assistant.plugins.reload import _reload_lock, start_replacement_registry
from vcenter_event_assistant.plugins.remote import CollectorWorkerServiceError, RemoteCollectorPlugin
from vcenter_event_assistant.services.plugin_configuration import (
    run_setup,
    schema_error,
    validate_values,
    validate_targets,
)
from vcenter_event_assistant.services.plugin_installs import prune_retired_plugin_generations
from vcenter_event_assistant.services.plugin_settings import load_collector_db_overrides
from vcenter_event_assistant.services.ssh_management import (
    reference_digest,
)
from vcenter_event_assistant.settings import Settings


async def mutation_gate():
    async with _reload_lock:
        yield


router = APIRouter(
    prefix="/plugins",
    tags=["plugin setup"],
    dependencies=[RequireAdmin],
    route_class=PluginSetupRoute,
)


def registration(plugin_id):
    r = get_collector_registry().get(plugin_id)
    if r is None or r.plugin is None:
        raise HTTPException(404, "プラグインが見つかりません。")
    if r.env_conflict:
        raise HTTPException(409, r.error)
    return r


def definition(r):
    manifest = r.plugin.manifest
    return {
        "schema": manifest.configuration_schema,
        "unavailable_reason": schema_error(manifest.configuration_schema),
        "actions": [
            {"id": a.id, "title": a.title, "required_for_enable": a.required_for_enable}
            for a in manifest.setup_actions
        ],
        "env_locked_fields": list(r.env_locked_fields),
    }


def draft_read(d):
    return {"config_values": d.config_values, "revision": d.revision, "tests": d.tests}


class DraftInput(BaseModel):
    config_values: dict = Field(default_factory=dict)
    revision: int | None = None


class RevisionInput(BaseModel):
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
async def validate_draft(
    plugin_id: str, session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
):
    r = registration(plugin_id)
    d = await session.get(PluginConfigurationDraft, plugin_id)
    if not d:
        raise HTTPException(422, "下書きを保存してください。")
    try:
        validate_values(
            d.config_values, r.plugin.manifest.configuration_schema,
            allow_legacy_ssh=not (settings.plugin_service_socket_dir and isinstance(r.plugin, RemoteCollectorPlugin)),
        )
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
            session, d.config_values, r.plugin.manifest.configuration_schema,
            allow_legacy=not (settings.plugin_service_socket_dir and isinstance(r.plugin, RemoteCollectorPlugin)),
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
        validate_values(
            d.config_values, r.plugin.manifest.configuration_schema,
            allow_legacy_ssh=not (settings.plugin_service_socket_dir and isinstance(r.plugin, RemoteCollectorPlugin)),
        )
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
    try:
        candidate = await start_replacement_registry(settings, candidate)
    except CollectorWorkerServiceError as exc:
        raise HTTPException(503, "プラグイン検出に失敗しました。現在の設定は維持されています。") from exc
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
    applied = candidate.get(plugin_id)
    if failures or applied is None or applied.status != "enabled":
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
    await prune_retired_plugin_generations(settings, candidate)
    return {"ok": True, "generation": candidate.generation}


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


router.include_router(
    ssh_setup_router(
        "logs",
        route_class=PluginSetupRoute,
        mutation_dependencies=[Depends(mutation_gate)],
        ensure_not_active=ensure_not_active,
    )
)
router.add_api_route("/vcenters/{identifier}/hosts", list_hosts, methods=["GET"])
