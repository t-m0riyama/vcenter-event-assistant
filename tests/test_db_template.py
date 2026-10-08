"""The test DB template preserves migrated schemas and per-test isolation."""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from vcenter_event_assistant.db.session import get_engine
from vcenter_event_assistant.db.startup_migration import run_startup_migration
from vcenter_event_assistant.settings import Settings


async def schema(engine: AsyncEngine) -> list[tuple]:
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
            )
        )
        return [tuple(row) for row in result]


async def test_template_matches_actual_migration(
    load_db_template: Callable[[AsyncEngine], Awaitable[None]],
) -> None:
    settings = Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:")
    migrated = create_async_engine(settings.database_url, poolclass=StaticPool)
    copied = create_async_engine(
        settings.database_url,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    try:
        await run_startup_migration(migrated, settings=settings)
        await load_db_template(copied)
        assert await schema(copied) == await schema(migrated)
        async with migrated.connect() as original, copied.connect() as clone:
            revision_sql = text("SELECT version_num FROM alembic_version")
            assert await clone.scalar(revision_sql) == await original.scalar(
                revision_sql
            )
    finally:
        await copied.dispose()
        await migrated.dispose()


async def test_template_copies_do_not_share_data_or_schema(
    load_db_template: Callable[[AsyncEngine], Awaitable[None]],
) -> None:
    first = get_engine()
    second = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    expected_schema = await schema(first)
    try:
        async with first.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO vcenters "
                    "(id, name, host, protocol, port, username, password, verify_ssl, is_enabled, created_at) "
                    "VALUES ('11111111111111111111111111111111', 'test', 'host', 'https', "
                    "443, 'user', 'password', 1, 1, CURRENT_TIMESTAMP)"
                )
            )
            await connection.execute(text("CREATE TABLE template_probe (value TEXT)"))
            await connection.execute(
                text("INSERT INTO template_probe VALUES ('first')")
            )
            await connection.execute(
                text("DROP INDEX ix_events_vcenter_id_occurred_at")
            )
        await load_db_template(second)
        assert await schema(second) == expected_schema
        async with second.connect() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM vcenters")) == 0
        # Copy again after modifying the first target: the source must still be pristine.
        await load_db_template(second)
        assert await schema(second) == expected_schema
        async with first.connect() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM vcenters")) == 1
    finally:
        await second.dispose()


async def test_template_foreign_keys_are_enforced() -> None:
    engine = get_engine()
    async with engine.begin() as connection:
        assert await connection.scalar(text("PRAGMA foreign_keys")) == 1
        await connection.execute(
            text(
                "CREATE TABLE template_child (vcenter_id BLOB REFERENCES vcenters(id))"
            )
        )
        with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
            await connection.execute(
                text("INSERT INTO template_child VALUES ('missing')")
            )
