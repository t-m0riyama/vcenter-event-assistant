"""SQLite / dedicated PostgreSQL startup migration integration tests."""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import sqlite3
import sys
from contextlib import closing
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from vcenter_event_assistant.db.alembic_runner import (
    _run_with_connection,
    alembic_config,
    get_alembic_head,
    get_applied_alembic_revision,
)
from vcenter_event_assistant.db.startup_migration import (
    BACKUP_SUFFIX,
    DbMigrationError,
    DbMigrationLockTimeoutError,
    backup_sqlite,
    postgres_migration_lock,
    prune_backups,
    run_startup_migration,
    sqlite_migration_lock,
)
from vcenter_event_assistant.settings import Settings

pytestmark = pytest.mark.real_db_init

WORKER = """
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from vcenter_event_assistant.settings import Settings
from vcenter_event_assistant.db.startup_migration import run_startup_migration
async def main():
    settings = Settings(_env_file=None, database_url=os.environ["VEA_MIGRATION_TEST_URL"])
    engine = create_async_engine(settings.database_url)
    try:
        await run_startup_migration(engine, settings=settings)
    finally:
        await engine.dispose()
asyncio.run(main())
"""


async def worker(url: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        WORKER,
        env={**os.environ, "VEA_MIGRATION_TEST_URL": url},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), 60)
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    assert proc.returncode == 0, (stdout + stderr).decode()


async def upgrade(engine, settings, revision):
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: _run_with_connection(
                c,
                alembic_config(settings=settings),
                lambda cfg: command.upgrade(cfg, revision),
            )
        )


@pytest.fixture
async def sqlite_db(tmp_path):
    path = tmp_path / "nested" / "vea.db"
    settings = Settings(_env_file=None, database_url=f"sqlite+aiosqlite:///{path}")
    engine = create_async_engine(settings.database_url)
    try:
        yield path, settings, engine
    finally:
        await engine.dispose()


async def test_sqlite_upgrade_backup_and_noop(sqlite_db, caplog):
    path, settings, engine = sqlite_db
    path.parent.mkdir()
    await upgrade(engine, settings, "c4d27748ae50")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO vcenters (id,name,host,port,username,password,is_enabled,created_at) "
                "VALUES (:id,'test','host',443,'user','secret',1,CURRENT_TIMESTAMP)"
            ),
            {"id": uuid4().hex},
        )
    caplog.set_level(logging.INFO)
    await run_startup_migration(engine, settings=settings)
    backups = list((path.parent / "backups").iterdir())
    assert len(backups) == 1
    assert backups[0].stat().st_mode & 0o777 == 0o600
    with closing(sqlite3.connect(backups[0])) as db:
        assert (
            db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "c4d27748ae50"
        )
        assert db.execute("SELECT name FROM vcenters").fetchone()[0] == "test"
    assert await get_applied_alembic_revision(engine) == get_alembic_head(
        settings=settings
    )
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT name FROM vcenters")) == "test"
    await run_startup_migration(engine, settings=settings)
    assert list((path.parent / "backups").iterdir()) == backups
    assert "DB_MIGRATION_COMPLETED" in caplog.text
    assert "reason=already_at_head" in caplog.text
    assert "secret" not in caplog.text


async def test_sqlite_concurrent_new_database(sqlite_db):
    path, settings, engine = sqlite_db
    await asyncio.gather(worker(settings.database_url), worker(settings.database_url))
    assert await get_applied_alembic_revision(engine) == get_alembic_head(
        settings=settings
    )
    assert not (path.parent / "backups").exists()


async def test_sqlite_concurrent_upgrade_only_one_backup(sqlite_db):
    path, settings, engine = sqlite_db
    path.parent.mkdir()
    await upgrade(engine, settings, "c4d27748ae50")
    await asyncio.gather(worker(settings.database_url), worker(settings.database_url))
    assert len(list((path.parent / "backups").iterdir())) == 1
    assert await get_applied_alembic_revision(engine) == get_alembic_head(
        settings=settings
    )


async def test_disabled_requires_head(sqlite_db):
    path, settings, engine = sqlite_db
    disabled = settings.model_copy(update={"vea_db_auto_migrate": False})
    with pytest.raises(DbMigrationError, match="does not exist"):
        await run_startup_migration(engine, settings=disabled)
    assert not path.exists()
    path.parent.mkdir()
    await upgrade(engine, settings, "c4d27748ae50")
    with pytest.raises(DbMigrationError, match="disabled"):
        await run_startup_migration(engine, settings=disabled)
    assert not (path.parent / "backups").exists()
    await run_startup_migration(engine, settings=settings)
    await run_startup_migration(engine, settings=disabled)


async def test_legacy_backup_precedes_stamp(sqlite_db):
    path, settings, engine = sqlite_db
    path.parent.mkdir()
    await upgrade(engine, settings, "c4d27748ae50")
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE alembic_version"))
    await run_startup_migration(engine, settings=settings)
    backup = next((path.parent / "backups").iterdir())
    with closing(sqlite3.connect(backup)) as db:
        tables = {
            r[0]
            for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "vcenters" in tables
        assert "alembic_version" not in tables
    assert await get_applied_alembic_revision(engine) == get_alembic_head(
        settings=settings
    )


async def test_unknown_revision_aborts_without_changes(sqlite_db, caplog):
    path, settings, engine = sqlite_db
    path.parent.mkdir()
    await upgrade(engine, settings, "c4d27748ae50")
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE alembic_version SET version_num='unknown_revision'")
        )
    with pytest.raises(DbMigrationError):
        await run_startup_migration(engine, settings=settings)
    assert not (path.parent / "backups").exists()
    assert await get_applied_alembic_revision(engine) == "unknown_revision"
    assert "DB_MIGRATION_FAILED" in caplog.text


async def test_multiple_heads_aborts(sqlite_db, monkeypatch):
    path, settings, engine = sqlite_db
    monkeypatch.setattr(
        "alembic.script.ScriptDirectory.get_heads", lambda _: ["one", "two"]
    )
    with pytest.raises(DbMigrationError):
        await run_startup_migration(engine, settings=settings)
    assert not (path.parent / "backups").exists()


async def test_memory_disabled_rejects_empty_db():
    settings = Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        vea_db_auto_migrate=False,
    )
    engine = create_async_engine(settings.database_url)
    try:
        with pytest.raises(DbMigrationError, match="disabled"):
            await run_startup_migration(engine, settings=settings)
    finally:
        await engine.dispose()


async def test_lock_timeout_and_cancellation_release(tmp_path):
    lock = tmp_path / "migration.lock"
    async with sqlite_migration_lock(lock, 0):
        with pytest.raises(DbMigrationLockTimeoutError):
            async with sqlite_migration_lock(lock, 0):
                pytest.fail("lock must exclude another opener")
    acquired = asyncio.Event()

    async def holder():
        async with sqlite_migration_lock(lock, 0):
            acquired.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(holder())
    await acquired.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with sqlite_migration_lock(lock, 0):
        pass


async def test_backup_failure_prevents_upgrade(sqlite_db, monkeypatch):
    path, settings, engine = sqlite_db
    path.parent.mkdir()
    await upgrade(engine, settings, "c4d27748ae50")

    def fail(_):
        raise OSError("sensitive connection detail")

    monkeypatch.setattr(
        "vcenter_event_assistant.db.startup_migration.backup_sqlite", fail
    )
    with pytest.raises(DbMigrationError, match="OSError") as error:
        await run_startup_migration(engine, settings=settings)
    assert "sensitive" not in str(error.value)
    assert await get_applied_alembic_revision(engine) == "c4d27748ae50"
    async with sqlite_migration_lock(path.with_name(path.name + ".migrate.lock"), 0):
        pass


async def test_upgrade_failure_keeps_backup_and_releases_lock(sqlite_db, monkeypatch):
    path, settings, engine = sqlite_db
    path.parent.mkdir()
    await upgrade(engine, settings, "c4d27748ae50")

    async def fail(*args, **kwargs):
        raise RuntimeError("secret")

    monkeypatch.setattr(
        "vcenter_event_assistant.db.startup_migration.alembic_upgrade_head", fail
    )
    with pytest.raises(DbMigrationError):
        await run_startup_migration(engine, settings=settings)
    assert len(list((path.parent / "backups").iterdir())) == 1
    async with sqlite_migration_lock(path.with_name(path.name + ".migrate.lock"), 0):
        pass


def test_backup_includes_wal_and_prunes_only_automatic_files(tmp_path):
    path = tmp_path / "db.sqlite"
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("CREATE TABLE sample (value TEXT)")
        db.execute("INSERT INTO sample VALUES ('wal-data')")
        db.commit()
        target = backup_sqlite(path)
        with closing(sqlite3.connect(target)) as snapshot:
            assert (
                snapshot.execute("SELECT value FROM sample").fetchone()[0] == "wal-data"
            )
        other = target.parent / ("other.db.000" + BACKUP_SUFFIX)
        other.touch()
        manual = target.parent / "db.sqlite.manual.bak"
        manual.touch()
        backup_sqlite(path)
        prune_backups(path, 0)
        assert len(list(target.parent.iterdir())) == 4
        prune_backups(path, 1)
        assert not target.exists()
        assert manual.exists() and other.exists()


@pytest.mark.parametrize(
    "field", ["vea_db_migration_lock_timeout_secs", "vea_db_backup_generations"]
)
def test_negative_settings_rejected(field):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **{field: -1})


async def test_lifespan_stops_before_followup_initialization(monkeypatch):
    # The CLI tests reload the package and replace its `main` attribute with the
    # CLI function. Patch the actual submodule, independent of execution order.
    app_module = importlib.import_module("vcenter_event_assistant.main")

    called = []

    async def fail(**kwargs):
        raise DbMigrationError("migration failed")

    async def followup(**kwargs):
        called.append(True)

    monkeypatch.setattr(app_module, "init_db", fail)
    monkeypatch.setattr(app_module, "ensure_secret_storage", followup)
    with pytest.raises(DbMigrationError):
        async with app_module.lifespan(app_module.create_app()):
            pytest.fail("application must not accept requests")
    assert called == []


@pytest.fixture
async def postgres_db():
    url = os.environ.get("VEA_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("VEA_TEST_POSTGRES_URL must point to a dedicated test database")
    engine = create_async_engine(url)
    settings = Settings(_env_file=None, database_url=url)
    # This fixture owns a dedicated database, never the configured application DB.
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    try:
        yield settings, engine
    finally:
        await engine.dispose()


async def test_postgres_concurrent_creation_and_upgrade(postgres_db):
    settings, engine = postgres_db
    await asyncio.gather(worker(settings.database_url), worker(settings.database_url))
    assert await get_applied_alembic_revision(engine) == get_alembic_head(
        settings=settings
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: _run_with_connection(
                c,
                alembic_config(settings=settings),
                lambda cfg: command.downgrade(cfg, "v3w4x5y6z7a8"),
            )
        )
    await asyncio.gather(worker(settings.database_url), worker(settings.database_url))
    assert await get_applied_alembic_revision(engine) == get_alembic_head(
        settings=settings
    )


async def test_postgres_timeout_failure_and_cancel_release(postgres_db):
    _, engine = postgres_db
    async with engine.connect() as first, engine.connect() as second:
        async with postgres_migration_lock(first, 0):
            with pytest.raises(DbMigrationLockTimeoutError):
                async with postgres_migration_lock(second, 0):
                    pytest.fail("lock is already held")
        with pytest.raises(RuntimeError):
            async with postgres_migration_lock(first, 0):
                raise RuntimeError("failed migration")
        async with postgres_migration_lock(second, 0):
            pass
        acquired = asyncio.Event()

        async def holder():
            async with postgres_migration_lock(first, 0):
                acquired.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(holder())
        await acquired.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with postgres_migration_lock(second, 0):
            pass


async def test_directory_downgrade_removes_directory_users_and_sessions(sqlite_db):
    """ディレクトリ機能を戻したら、そのユーザーとセッションを残さない（ローカルのユーザーは残す）。"""
    path, settings, engine = sqlite_db
    path.parent.mkdir(parents=True, exist_ok=True)
    await upgrade(engine, settings, "a8b9c0d1e2f3")
    now = "2026-01-01 00:00:00"
    async with engine.begin() as conn:
        for user_id, realm in (("u-local", "local"), ("u-dir", "dir:abc")):
            await conn.execute(
                text(
                    "INSERT INTO users (id, realm_key, subject, username, role, is_active, "
                    "failed_login_count, created_at, updated_at) "
                    "VALUES (:id, :realm, :id, :id, 'admin', 1, 0, :now, :now)"
                ),
                {"id": user_id, "realm": realm, "now": now},
            )
            await conn.execute(
                text(
                    "INSERT INTO auth_sessions (id, token_hash, user_id, created_at, last_seen_at, "
                    "expires_at) VALUES (:sid, :sid, :id, :now, :now, :now)"
                ),
                {"sid": f"s-{user_id}", "id": user_id, "now": now},
            )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: _run_with_connection(
                c,
                alembic_config(settings=settings),
                lambda cfg: command.downgrade(cfg, "z7a8b9c0d1e2"),
            )
        )
    async with engine.connect() as conn:
        users = (await conn.execute(text("SELECT id FROM users"))).scalars().all()
        sessions = (await conn.execute(text("SELECT user_id FROM auth_sessions"))).scalars().all()
    assert users == ["u-local"]
    assert sessions == ["u-local"]
