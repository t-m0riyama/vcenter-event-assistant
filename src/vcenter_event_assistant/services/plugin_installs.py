"""Background installation jobs and the installed-plugin inventory.

インストールは数十秒かかりうるためリクエストの中では完結させず、``installed_plugins``
行の ``status`` を進めるバックグラウンドタスクとして実行する。UI はポーリングする。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import InstalledPlugin
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.plugins.installer import (
    PluginInstallError,
    install_plugin,
    uninstall_plugin,
)
from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)

# 稼働中のインストールタスク。イベントループが破棄されるまでの弱い参照切れを防ぐ。
_tasks: set[asyncio.Task] = set()

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
    existing = (
        await session.execute(
            select(InstalledPlugin).where(InstalledPlugin.distribution == distribution)
        )
    ).scalar_one_or_none()
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
        message = (
            str(exc)
            if isinstance(exc, PluginInstallError)
            else f"installation failed: {type(exc).__name__}"
        )
        logger.exception("plugin installation job failed distribution=%s", distribution)
        async with session_scope(settings=settings) as session:
            await _upsert(
                session, distribution, status="failed", error_message=message[:1000]
            )
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
    removed = await asyncio.to_thread(uninstall_plugin, settings, distribution)
    row = (
        await session.execute(
            select(InstalledPlugin).where(InstalledPlugin.distribution == distribution)
        )
    ).scalar_one_or_none()
    if row is not None:
        await session.delete(row)
    return removed or row is not None


async def wait_for_installs() -> None:
    """テストと graceful shutdown 用に、稼働中のインストールを待つ。"""
    if _tasks:
        await asyncio.gather(*tuple(_tasks), return_exceptions=True)
