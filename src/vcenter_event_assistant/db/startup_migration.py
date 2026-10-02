"""排他制御と SQLite バックアップを伴う起動時スキーマ更新。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import sqlite3
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from vcenter_event_assistant.db.alembic_runner import (
    LegacySchemaStampError,
    alembic_config,
    alembic_stamp,
    alembic_upgrade_head,
    get_alembic_head,
    get_applied_alembic_revision,
    infer_legacy_stamp_revision,
)
from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)
BACKUP_SUFFIX = ".pre-migrate.bak"
LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"VEA schema migration").digest()[:8], "big", signed=True
)
POLL_SECONDS = 0.1


class DbMigrationError(RuntimeError):
    """DB を安全に最新化できないため起動できない。"""


class DbMigrationLockTimeoutError(DbMigrationError):
    """他プロセスの移行完了待ちが上限を超えた。"""


@asynccontextmanager
async def sqlite_migration_lock(path: Path, timeout: int) -> AsyncIterator[None]:
    try:
        import fcntl
    except ImportError:
        raise DbMigrationError(
            "SQLite migration locking is unavailable on this platform"
        ) from None
    deadline = time.monotonic() + timeout
    with path.open("a+b") as lock:
        while True:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise DbMigrationLockTimeoutError(
                        "SQLite migration lock timed out"
                    ) from None
                await asyncio.sleep(POLL_SECONDS)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


@asynccontextmanager
async def postgres_migration_lock(
    conn: AsyncConnection, timeout: int
) -> AsyncIterator[None]:
    deadline = time.monotonic() + timeout
    # All transactions, including Alembic, run on this same physical connection.
    try:
        while True:
            acquired = await conn.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}
            )
            await conn.commit()
            if acquired:
                break
            if time.monotonic() >= deadline:
                raise DbMigrationLockTimeoutError("PostgreSQL migration lock timed out")
            await asyncio.sleep(POLL_SECONDS)
        yield
    finally:
        # Unlock even if cancellation arrives just after the server acquired the lock.
        async def release() -> None:
            try:
                await conn.rollback()
                await conn.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY}
                )
                await conn.commit()
            except BaseException:
                # Never return a connection holding a session lock to the pool.
                await conn.invalidate()
                raise

        task = asyncio.create_task(release())
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise


def backup_sqlite(path: Path) -> Path:
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    target = backup_dir / f"{path.name}.{timestamp}.{uuid4().hex}{BACKUP_SUFFIX}"
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with closing(
            sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        ) as source:
            with closing(sqlite3.connect(target)) as destination:
                source.backup(destination)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def prune_backups(path: Path, generations: int) -> None:
    if generations == 0:
        return
    # Match exactly our generated names; another DB or a manual .bak is not ours.
    pattern = re.compile(
        re.escape(path.name) + r"\.\d{20}\.[0-9a-f]{32}" + re.escape(BACKUP_SUFFIX)
    )
    backups = sorted(
        (p for p in (path.parent / "backups").iterdir() if pattern.fullmatch(p.name)),
        reverse=True,
    )
    for stale in backups[generations:]:
        stale.unlink()


async def _backup(path: Path) -> Path:
    task = asyncio.create_task(asyncio.to_thread(backup_sqlite, path))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # A background backup must finish before the file lock is released.
        await task
        raise


async def _migrate(
    conn: AsyncConnection, path: Path | None, settings: Settings
) -> None:
    try:
        head = get_alembic_head(settings=settings)
    except RuntimeError:
        raise DbMigrationError(
            "Migration scripts must contain exactly one head"
        ) from None
    try:
        current = await get_applied_alembic_revision(conn)
    except CommandError:
        raise DbMigrationError(
            "Database has multiple applied revisions; manual recovery required"
        ) from None
    if current == head:
        await conn.rollback()
        logger.info("DB_MIGRATION_SKIPPED reason=already_at_head revision=%s", head)
        return
    if not settings.vea_db_auto_migrate:
        raise DbMigrationError(
            "Automatic migration disabled; run alembic upgrade head before startup"
        )
    if current is not None:
        script = ScriptDirectory.from_config(alembic_config(settings=settings))
        try:
            known = script.get_revision(current)
        except CommandError:
            raise DbMigrationError(
                "Database revision is not present in the migration scripts"
            ) from None
        if known is None:
            raise DbMigrationError("Unknown database revision")
    stamp = await infer_legacy_stamp_revision(conn) if current is None else None
    has_tables = await conn.run_sync(lambda c: bool(inspect(c).get_table_names()))
    await conn.rollback()  # End introspection transaction before backup/stamp/upgrade.
    if path is not None and has_tables:
        backup = await _backup(path)
        logger.info("DB_MIGRATION_BACKUP_CREATED path=%s", backup)
    logger.info("DB_MIGRATION_STARTED from_revision=%s to_revision=%s", current, head)
    if stamp is not None:
        await alembic_stamp(conn, stamp, settings=settings)
    await alembic_upgrade_head(conn, settings=settings)
    if await get_applied_alembic_revision(conn) != head:
        raise DbMigrationError("Migration completed without reaching head")
    await conn.rollback()
    logger.info("DB_MIGRATION_COMPLETED revision=%s", head)
    if path is not None and has_tables:
        try:
            await asyncio.to_thread(
                prune_backups, path, settings.vea_db_backup_generations
            )
        except OSError:
            logger.warning("DB_MIGRATION_BACKUP_PRUNE_FAILED")


async def run_startup_migration(engine: AsyncEngine, *, settings: Settings) -> None:
    url = engine.url
    path = None
    if url.get_backend_name() == "sqlite" and url.database not in (
        None,
        "",
        ":memory:",
    ):
        path = Path(url.database).resolve()
    timeout = settings.vea_db_migration_lock_timeout_secs

    async def connected() -> None:
        async with engine.connect() as conn:
            if conn.dialect.name == "postgresql":
                async with postgres_migration_lock(conn, timeout):
                    await _migrate(conn, path, settings)
            else:
                await _migrate(conn, path, settings)

    try:
        if path is not None:
            if not settings.vea_db_auto_migrate and not path.exists():
                raise DbMigrationError(
                    "Automatic migration disabled; database does not exist"
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            async with sqlite_migration_lock(
                path.with_name(path.name + ".migrate.lock"), timeout
            ):
                await connected()
        else:
            await connected()
    except asyncio.CancelledError:
        logger.warning("DB_MIGRATION_CANCELLED")
        raise
    except (DbMigrationError, LegacySchemaStampError) as exc:
        logger.error("DB_MIGRATION_FAILED reason=%s; see docs/development.md", exc)
        raise
    except Exception as exc:
        # Driver/SQL exceptions may contain credentials, URLs or stored data.
        logger.error("DB_MIGRATION_FAILED error_type=%s", type(exc).__name__)
        raise DbMigrationError(
            f"Database migration failed ({type(exc).__name__}); see docs/development.md"
        ) from None
