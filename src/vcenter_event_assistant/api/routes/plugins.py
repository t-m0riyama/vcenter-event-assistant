"""Collector plugin status and management API."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.deps import get_app_settings, get_session
from vcenter_event_assistant.api.schemas.plugins import (
    CollectorReloadResponse,
    CollectorRunStatusRead,
    CollectorSettingUpdate,
    CollectorStatusListResponse,
    CollectorStatusRead,
    InstalledPluginListResponse,
    InstalledPluginRead,
    PluginInstallRequest,
)
from vcenter_event_assistant.db.models import CollectorRunState, VCenter
from vcenter_event_assistant.plugins.config import collector_env_locked_fields
from vcenter_event_assistant.plugins.installer import (
    MAX_UPLOAD_BYTES,
    PluginInstallError,
    parse_requirement,
    parse_upload_filename,
)
from vcenter_event_assistant.plugins.registry import (
    CollectorRegistry,
    get_collector_registry,
)
from vcenter_event_assistant.plugins.reload import reload_collector_registry
from vcenter_event_assistant.services.plugin_installs import (
    list_installed_plugins,
    remove_installed_plugin,
    start_install,
)
from vcenter_event_assistant.services.plugin_settings import (
    load_collector_db_overrides,
    update_collector_setting,
)
from vcenter_event_assistant.settings import Settings

router = APIRouter(prefix="/plugins/collectors", tags=["plugins"])
installed_router = APIRouter(prefix="/plugins/installed", tags=["plugins"])


def _require_management_enabled(settings: Settings) -> None:
    """変更系エンドポイントのゲート。

    プラグイン管理は実質的に任意コード実行を許すため、既定では無効であり、
    無効時はエンドポイントの存在自体を伏せて 404 を返す。
    """
    if not settings.plugin_management_enabled:
        raise HTTPException(status_code=404, detail="Not Found")


async def _run_statuses_by_plugin(
    session: AsyncSession,
) -> dict[str, list[CollectorRunStatusRead]]:
    result = await session.execute(
        select(CollectorRunState, VCenter.name)
        .join(VCenter, VCenter.id == CollectorRunState.vcenter_id)
        .order_by(
            CollectorRunState.collector_id.asc(),
            VCenter.name.asc(),
            CollectorRunState.vcenter_id.asc(),
        )
    )
    by_plugin: dict[str, list[CollectorRunStatusRead]] = {}
    for state, vcenter_name in result.all():
        by_plugin.setdefault(state.collector_id, []).append(
            CollectorRunStatusRead(
                vcenter_id=state.vcenter_id,
                vcenter_name=vcenter_name,
                status=state.status,
                collector_version=state.collector_version,
                last_started_at=state.last_started_at,
                last_success_at=state.last_success_at,
                last_failure_at=state.last_failure_at,
                events_inserted=state.events_inserted,
                metrics_inserted=state.metrics_inserted,
                error=state.error_message,
            )
        )
    return by_plugin


def _collector_reads(
    registry: CollectorRegistry,
    runs_by_plugin: dict[str, list[CollectorRunStatusRead]],
) -> list[CollectorStatusRead]:
    collectors: list[CollectorStatusRead] = []
    for registration in sorted(
        registry.registrations.values(), key=lambda item: item.plugin_id
    ):
        manifest = registration.plugin.manifest if registration.plugin else None
        collectors.append(
            CollectorStatusRead(
                id=registration.plugin_id,
                display_name=manifest.display_name if manifest else None,
                source=registration.source,
                status=registration.status,
                error=registration.error,
                version=manifest.version if manifest else None,
                api_version=manifest.api_version if manifest else None,
                data_kinds=sorted(manifest.data_kinds) if manifest else [],
                interval_seconds=registration.config.interval_seconds
                if registration.config
                else None,
                timeout_seconds=registration.config.timeout_seconds
                if registration.config
                else None,
                env_locked_fields=collector_env_locked_fields(registration.plugin_id),
                runs=runs_by_plugin.get(registration.plugin_id, []),
            )
        )
    return collectors


def _reload_required(
    registry: CollectorRegistry, overrides: dict[str, dict]
) -> bool:
    """DB の保存値が稼働中の世代に未反映かどうか。

    環境変数でロックされたフィールドは DB 値が適用されないのが正しい挙動なので、
    未反映として数えない。
    """
    for plugin_id, values in overrides.items():
        registration = registry.get(plugin_id)
        if registration is None or registration.config is None:
            # 未インストール、または設定が組み立てられなかったものは判定対象外。
            continue
        locked = set(collector_env_locked_fields(plugin_id))
        config = registration.config
        effective = {
            "enabled": registration.status == "enabled",
            "interval_seconds": config.interval_seconds,
            "timeout_seconds": config.timeout_seconds,
        }
        for field_name, desired in values.items():
            if field_name in locked or field_name not in effective:
                continue
            if effective[field_name] != desired:
                return True
    return False


@router.get("", response_model=CollectorStatusListResponse)
async def list_collectors(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> CollectorStatusListResponse:
    registry = get_collector_registry()
    runs_by_plugin = await _run_statuses_by_plugin(session)
    overrides = await load_collector_db_overrides(session)
    return CollectorStatusListResponse(
        generation=registry.generation,
        management_enabled=settings.plugin_management_enabled,
        reload_required=_reload_required(registry, overrides),
        collectors=_collector_reads(registry, runs_by_plugin),
    )


@router.patch("/{plugin_id}", response_model=CollectorStatusListResponse)
async def update_collector(
    plugin_id: str,
    payload: CollectorSettingUpdate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> CollectorStatusListResponse:
    """設定を DB に保存する。稼働中の世代への反映は明示的なリロードで行う。"""
    _require_management_enabled(settings)
    registry = get_collector_registry()
    if registry.get(plugin_id) is None:
        raise HTTPException(status_code=404, detail="collector is not registered")
    try:
        await update_collector_setting(
            session,
            plugin_id,
            enabled=payload.enabled,
            interval_seconds=payload.interval_seconds,
            timeout_seconds=payload.timeout_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    runs_by_plugin = await _run_statuses_by_plugin(session)
    overrides = await load_collector_db_overrides(session)
    return CollectorStatusListResponse(
        generation=registry.generation,
        management_enabled=True,
        reload_required=_reload_required(registry, overrides),
        collectors=_collector_reads(registry, runs_by_plugin),
    )


@router.post("/reload", response_model=CollectorReloadResponse)
async def reload_collectors(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> CollectorReloadResponse:
    """レジストリを再構築して原子的に差し替え、スケジューラのジョブを追従させる。"""
    _require_management_enabled(settings)
    result = await reload_collector_registry(
        settings, scheduler=getattr(request.app.state, "scheduler", None)
    )
    registry = get_collector_registry()
    runs_by_plugin = await _run_statuses_by_plugin(session)
    return CollectorReloadResponse(
        generation=result.generation,
        jobs_added=result.job_changes["added"],
        jobs_removed=result.job_changes["removed"],
        jobs_rescheduled=result.job_changes["rescheduled"],
        collectors=_collector_reads(registry, runs_by_plugin),
    )


def _installed_reads(rows) -> list[InstalledPluginRead]:
    return [
        InstalledPluginRead(
            distribution=row.distribution,
            version=row.version,
            source=row.source,
            origin=row.origin,
            status=row.status,
            error=row.error_message,
            installed_at=row.installed_at,
        )
        for row in rows
    ]


@installed_router.get("", response_model=InstalledPluginListResponse)
async def list_installed(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> InstalledPluginListResponse:
    """インストール済み・進行中・失敗した配布物の一覧。"""
    _require_management_enabled(settings)
    rows = await list_installed_plugins(session)
    return InstalledPluginListResponse(
        management_enabled=True,
        index_install_enabled=settings.plugin_allow_index_install,
        plugins=_installed_reads(rows),
    )


@installed_router.post("", response_model=InstalledPluginListResponse, status_code=202)
async def install_from_index(
    payload: PluginInstallRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> InstalledPluginListResponse:
    """インデックスから名前指定でインストールする（既定では無効）。"""
    _require_management_enabled(settings)
    if not settings.plugin_allow_index_install:
        raise HTTPException(
            status_code=409,
            detail="installing from a package index is disabled",
        )
    try:
        distribution, version = parse_requirement(payload.requirement)
        requirement = f"{distribution}=={version}" if version else distribution
        await start_install(
            session,
            settings,
            distribution=distribution,
            source=requirement,
            origin=requirement,
            from_index=True,
        )
    except PluginInstallError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    rows = await list_installed_plugins(session)
    return InstalledPluginListResponse(
        management_enabled=True,
        index_install_enabled=True,
        plugins=_installed_reads(rows),
    )


@installed_router.post(
    "/upload", response_model=InstalledPluginListResponse, status_code=202
)
async def install_from_upload(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> InstalledPluginListResponse:
    """アップロードされた wheel / sdist をインストールする。"""
    _require_management_enabled(settings)
    try:
        distribution, _version = parse_upload_filename(file.filename or "")
    except PluginInstallError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    payload = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"plugin package exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB",
        )
    if not payload:
        raise HTTPException(status_code=422, detail="uploaded file is empty")

    # インストーラは自分で管理するパスだけを uv へ渡す（引数注入を避けるため）。
    staging_dir = Path(tempfile.mkdtemp(prefix="vea-plugin-upload-"))
    staged = staging_dir / Path(file.filename or "package").name
    staged.write_bytes(payload)

    try:
        await start_install(
            session,
            settings,
            distribution=distribution,
            source=str(staged),
            origin=Path(file.filename or "").name,
            from_index=False,
        )
    except PluginInstallError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    rows = await list_installed_plugins(session)
    return InstalledPluginListResponse(
        management_enabled=True,
        index_install_enabled=settings.plugin_allow_index_install,
        plugins=_installed_reads(rows),
    )


@installed_router.delete("/{distribution}", response_model=InstalledPluginListResponse)
async def uninstall(
    distribution: str,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> InstalledPluginListResponse:
    """配布物を削除する。稼働中の世代への反映には別途リロードが必要である。"""
    _require_management_enabled(settings)
    try:
        removed = await remove_installed_plugin(session, settings, distribution)
    except PluginInstallError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="plugin is not installed")

    rows = await list_installed_plugins(session)
    return InstalledPluginListResponse(
        management_enabled=True,
        index_install_enabled=settings.plugin_allow_index_install,
        plugins=_installed_reads(rows),
    )
