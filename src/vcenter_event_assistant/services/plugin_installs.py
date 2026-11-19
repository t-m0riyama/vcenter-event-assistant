"""Background installation jobs and the installed-plugin inventory.

インストールは数十秒かかりうるためリクエストの中では完結させず、``installed_plugins``
行の ``status`` を進めるバックグラウンドタスクとして実行する。UI はポーリングする。
"""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
import logging
import os
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import InstalledPlugin
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.plugins.installer import (
    PluginInstallError,
    install_plugin,
    normalize_distribution,
    uninstall_plugin,
)
from vcenter_event_assistant.plugins.publication import (
    clear_pending,
    installed_paths,
    published_paths,
    read_catalog,
    remove_retired_generations,
)
from vcenter_event_assistant.plugins.remote import RemoteCollectorPlugin
from vcenter_event_assistant.settings import Settings

if TYPE_CHECKING:
    from vcenter_event_assistant.plugins.registry import CollectorRegistry

logger = logging.getLogger(__name__)

# 稼働中のインストールタスク。イベントループが破棄されるまでの弱い参照切れを防ぐ。
_tasks: set[asyncio.Task] = set()
_publication_lock = asyncio.Lock()
_inventory_lock = asyncio.Lock()


class PluginPublicationBusyError(PluginInstallError):
    """An installation or publication recovery currently owns the catalog."""

_UPLOAD_DIR_PREFIX = "vea-plugin-upload-"
_UPLOAD_DIR_RE = re.compile(rf"{_UPLOAD_DIR_PREFIX}(\d+)-.+")
# プロセス ID を名前に持たない以前の形式のディレクトリは、作成から十分たったものだけ消す。
_LEGACY_UPLOAD_DIR_MAX_AGE_SECONDS = 86400


def create_upload_dir() -> Path:
    """アップロードされたパッケージを置く一時ディレクトリを作る。

    名前にプロセス ID を入れ、異常終了で残ったものを次の起動時に見分けられるようにする。
    """
    return Path(tempfile.mkdtemp(prefix=f"{_UPLOAD_DIR_PREFIX}{os.getpid()}-"))


def remove_upload_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def cleanup_stale_upload_dirs() -> None:
    """起動時に、終了したプロセスが残したアップロードの一時ディレクトリを消す（監査 L-1）。"""
    root = Path(tempfile.gettempdir())
    for path in root.glob(f"{_UPLOAD_DIR_PREFIX}*"):
        try:
            if path.is_symlink() or not path.is_dir() or path.stat().st_uid != os.getuid():
                continue
            match = _UPLOAD_DIR_RE.fullmatch(path.name)
            if match is None:
                if time.time() - path.stat().st_mtime > _LEGACY_UPLOAD_DIR_MAX_AGE_SECONDS:
                    remove_upload_dir(path)
                continue
            pid = int(match[1])
            if pid == os.getpid():
                continue
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                remove_upload_dir(path)
            except PermissionError:
                pass
        except OSError:
            logger.warning("failed to inspect plugin upload directory %s", path, exc_info=True)


async def list_installed_plugins(session: AsyncSession) -> list[InstalledPlugin]:
    result = await session.execute(
        select(InstalledPlugin).order_by(InstalledPlugin.distribution.asc())
    )
    return list(result.scalars().all())


async def _upsert(
    session: AsyncSession, distribution: str, **values
) -> InstalledPlugin:
    row = (
        await session.execute(
            select(InstalledPlugin).where(InstalledPlugin.distribution == distribution)
        )
    ).scalar_one_or_none()
    if row is None:
        row = InstalledPlugin(distribution=distribution, version="", source="", status="")
        session.add(row)
    for key, value in values.items():
        setattr(row, key, value)
    await session.flush()
    return row


async def start_install(
    session: AsyncSession,
    settings: Settings,
    *,
    distribution: str,
    source: str,
    origin: str,
    from_index: bool,
    upload_dir: Path | None = None,
) -> InstalledPlugin:
    """``installing`` 行を作り、実際のインストールをバックグラウンドへ投げる。

    ``upload_dir`` を渡すと、ジョブの終了時（成功・失敗とも）に削除する。
    この関数が例外を投げたときは削除しないので、呼び出し元が削除する。
    """
    async with (_inventory_lock if settings.plugin_service_socket_dir else nullcontext()):
        if settings.plugin_service_socket_dir:
            pending = read_catalog(Path(settings.plugin_dir).resolve())["pending"]
            if pending is not None and pending["distribution"] == distribution:
                raise PluginInstallError(f"publication for {distribution} is pending")
        existing = await session.scalar(
            select(InstalledPlugin).where(InstalledPlugin.distribution == distribution)
        )
        if existing is not None and existing.status == "installing":
            raise PluginInstallError(
                f"an installation of {distribution} is already in progress"
            )
        row = await _upsert(
            session,
            distribution,
            source="index" if from_index else "upload",
            origin=origin[:1024],
            status="installing",
            error_message=None,
            installed_at=datetime.now(timezone.utc),
        )
        await session.commit()

    task = asyncio.create_task(
        _run_install_job(
            settings,
            distribution=distribution,
            source=source,
            from_index=from_index,
            upload_dir=upload_dir,
        )
    )
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return row


async def _run_install_job(
    settings: Settings,
    *,
    distribution: str,
    source: str,
    from_index: bool,
    upload_dir: Path | None = None,
) -> None:
    try:
        async with _publication_lock:
            if settings.plugin_service_socket_dir:
                await _finish_publication(settings)
            await _install_and_record(
                settings, distribution=distribution, source=source, from_index=from_index
            )
    finally:
        if upload_dir is not None:
            await asyncio.to_thread(remove_upload_dir, upload_dir)


async def _install_and_record(
    settings: Settings, *, distribution: str, source: str, from_index: bool
) -> None:
    try:
        outcome = await install_plugin(
            settings, source=source, from_index=from_index
        )
    except Exception as exc:
        if settings.plugin_service_socket_dir:
            root = Path(settings.plugin_dir).resolve()
            if read_catalog(root)["pending"] is not None:
                await _finish_publication(settings)
                return
        message = (
            str(exc)
            if isinstance(exc, PluginInstallError)
            else f"installation failed: {type(exc).__name__}"
        )
        logger.exception("plugin installation job failed distribution=%s", distribution)
        async def record_failure() -> None:
            async with session_scope(settings=settings) as session:
                await _upsert(
                    session, distribution, status="failed", error_message=message[:1000]
                )

        if settings.plugin_service_socket_dir:
            await _retry_inventory_write(record_failure)
        else:
            await record_failure()
        return

    if settings.plugin_service_socket_dir:
        await _finish_publication(settings)
        return

    async with session_scope(settings=settings) as session:
        # uv が解決した実際の配布物名が要求と異なることがあるため、両方を整合させる。
        if outcome.distribution != distribution:
            stale = (
                await session.execute(
                    select(InstalledPlugin).where(
                        InstalledPlugin.distribution == distribution
                    )
                )
            ).scalar_one_or_none()
            if stale is not None:
                await session.delete(stale)
                await session.flush()
        await _upsert(
            session,
            outcome.distribution,
            version=outcome.version,
            source="index" if from_index else "upload",
            install_path=outcome.install_path,
            status="installed",
            error_message=None,
            installed_at=datetime.now(timezone.utc),
        )


async def remove_installed_plugin(
    session: AsyncSession, settings: Settings, distribution: str
) -> bool:
    """ディレクトリと台帳の行を削除する。反映には別途リロードが必要である。"""
    if settings.plugin_service_socket_dir:
        try:
            async with asyncio.timeout(0.1):
                await _publication_lock.acquire()
        except TimeoutError as exc:
            raise PluginPublicationBusyError("plugin publication is busy; retry uninstall") from exc
        try:
            await _reconcile_publication(settings)
            async with _inventory_lock:
                normalized = normalize_distribution(distribution.strip())
                row = await session.scalar(
                    select(InstalledPlugin).where(InstalledPlugin.distribution == normalized)
                )
                if row is not None and row.status == "installing":
                    raise PluginInstallError(f"an installation of {normalized} is already in progress")
                removed = uninstall_plugin(settings, distribution)
                if row is not None:
                    await session.delete(row)
                await session.commit()
                clear_pending(Path(settings.plugin_dir).resolve())
                return removed or row is not None
        finally:
            _publication_lock.release()
    removed = await asyncio.to_thread(uninstall_plugin, settings, distribution)
    row = (
        await session.execute(
            select(InstalledPlugin).where(InstalledPlugin.distribution == distribution)
        )
    ).scalar_one_or_none()
    if row is not None:
        await session.delete(row)
    return removed or row is not None


async def _reconcile_publication(settings: Settings) -> None:
    root = Path(settings.plugin_dir).resolve()
    pending = read_catalog(root)["pending"]
    if pending is None:
        return
    distribution = pending["distribution"]
    async with session_scope(settings=settings) as session:
        if pending["operation"] == "install":
            await _upsert(
                session, distribution, status="installed", version=pending["version"],
                source=pending["source"], install_path=pending["path"],
                error_message=None, installed_at=datetime.now(timezone.utc),
            )
        elif pending["operation"] == "uninstall":
            row = await session.scalar(
                select(InstalledPlugin).where(InstalledPlugin.distribution == distribution)
            )
            if row is not None:
                await session.delete(row)
        else:
            raise RuntimeError("unknown plugin publication operation")
    clear_pending(root)


async def _retry_inventory_write(operation: Callable[[], Awaitable[None]]) -> None:
    """Keep background jobs alive while DB or journal storage is unavailable."""
    delay = 0.25
    while True:
        try:
            await operation()
            return
        except (DBAPIError, OSError) as exc:
            if isinstance(exc, DBAPIError) and not (
                isinstance(exc, OperationalError) or exc.connection_invalidated
            ):
                raise
            if delay == 0.25:
                logger.warning("plugin inventory update will retry after %s", type(exc).__name__)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 10.0)


async def _finish_publication(settings: Settings) -> None:
    async def reconcile() -> None:
        async with _inventory_lock:
            await _reconcile_publication(settings)

    await _retry_inventory_write(reconcile)


async def recover_plugin_publication(settings: Settings) -> None:
    if not settings.plugin_service_socket_dir:
        return
    root = Path(settings.plugin_dir).resolve()
    versions = installed_paths(root)
    keep = set(versions.values())
    if any(not Path(path).is_dir() for path in keep):
        raise RuntimeError("published plugin directories are missing; verify the plugin volume")
    await _reconcile_publication(settings)
    async with session_scope(settings=settings) as session:
        rows = await session.scalars(select(InstalledPlugin))
        for row in rows:
            if row.status == "installing":
                row.status = "failed"
                row.error_message = "installation was interrupted"
            if migrated := versions.get((row.distribution, row.version)):
                row.install_path = migrated
    await asyncio.to_thread(remove_retired_generations, root, keep)
    await asyncio.to_thread(shutil.rmtree, root / ".staging", True)


async def prune_retired_plugin_generations(
    settings: Settings, registry: CollectorRegistry
) -> None:
    if not settings.plugin_service_socket_dir or _publication_lock.locked():
        return
    async with _publication_lock:
        root = Path(settings.plugin_dir).resolve()
        if read_catalog(root)["pending"] is not None:
            return
        keep = set(published_paths(root))
        for registration in registry.registrations.values():
            if isinstance(registration.plugin, RemoteCollectorPlugin):
                keep.update(registration.plugin.installed_paths)
        try:
            await asyncio.to_thread(remove_retired_generations, root, keep)
        except OSError:
            logger.warning("could not remove retired plugin versions", exc_info=True)


async def wait_for_installs() -> None:
    """テストと graceful shutdown 用に、稼働中のインストールを待つ。"""
    if _tasks:
        await asyncio.gather(*tuple(_tasks), return_exceptions=True)
