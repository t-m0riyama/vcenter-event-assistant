"""init_db の Alembic 一本化（2-1a / 2-1b）。"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

from vcenter_event_assistant.db.alembic_runner import (
    LegacySchemaStampError,
    get_alembic_head,
    get_applied_alembic_revision,
)
from vcenter_event_assistant.db.session import init_db, reset_db
from vcenter_event_assistant.settings import get_settings
from vcenter_event_assistant.settings_binding import bind_settings

pytestmark = pytest.mark.real_db_init


async def _alert_states_column_names(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as conn:
        result = await conn.execute(text("PRAGMA table_info(alert_states)"))
        return [row[1] for row in result.fetchall()]


@pytest.mark.asyncio
async def test_init_db_sets_alembic_head_on_fresh_db() -> None:
    """空 DB では ``upgrade head`` で全テーブルと ``alembic_version`` が作られる。"""
    await reset_db()
    await init_db()

    from vcenter_event_assistant.db.session import get_engine

    engine = get_engine()
    revision = await get_applied_alembic_revision(engine)
    assert revision == get_alembic_head()

    async with engine.connect() as conn:

        def sync_check(sync_conn) -> bool:
            insp = inspect(sync_conn)
            return insp.has_table("vcenters") and insp.has_table("incident_timeline_manual_snapshots")

        assert await conn.run_sync(sync_check)


@pytest.mark.asyncio
async def test_init_db_adds_alert_states_last_notified_at_on_legacy_schema(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``last_notified_at`` 列が無い旧 ``alert_states`` に対し ``init_db`` で列が追加される。"""
    db_path = tmp_path / "legacy.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    bind_settings(get_settings())

    await reset_db()
    await init_db()

    from vcenter_event_assistant.db.session import get_engine

    engine = get_engine()
    cols = await _alert_states_column_names(engine)
    assert "last_notified_at" in cols
    assert await get_applied_alembic_revision(engine) == get_alembic_head()

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE alert_states_legacy AS "
                "SELECT id, rule_id, state, context_key, fired_at, resolved_at FROM alert_states"
            )
        )
        await conn.execute(text("DROP TABLE alert_states"))
        await conn.execute(
            text(
                "CREATE TABLE alert_states ("
                "id INTEGER PRIMARY KEY, rule_id INTEGER NOT NULL, state VARCHAR(32) NOT NULL, "
                "context_key VARCHAR(512) NOT NULL, fired_at DATETIME NOT NULL, "
                "resolved_at DATETIME)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO alert_states "
                "(id, rule_id, state, context_key, fired_at, resolved_at) "
                "SELECT id, rule_id, state, context_key, fired_at, resolved_at FROM alert_states_legacy"
            )
        )
        await conn.execute(text("DROP TABLE alert_states_legacy"))
        await conn.execute(text("DELETE FROM alembic_version"))

    cols_before = await _alert_states_column_names(engine)
    assert "last_notified_at" not in cols_before

    await init_db()

    cols_after = await _alert_states_column_names(engine)
    assert "last_notified_at" in cols_after
    assert await get_applied_alembic_revision(engine) == get_alembic_head()

    await reset_db()


@pytest.mark.asyncio
async def test_init_db_aborts_on_ambiguous_legacy_schema(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """列 fingerprint が曖昧な旧 DB では起動 abort する。"""
    db_path = tmp_path / "ambiguous.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    bind_settings(get_settings())

    await reset_db()
    await init_db()

    from vcenter_event_assistant.db.session import get_engine

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM alembic_version"))
        await conn.execute(text("ALTER TABLE events RENAME TO events_legacy"))
        await conn.execute(
            text(
                "CREATE TABLE events ("
                "id INTEGER PRIMARY KEY, vcenter_id BLOB NOT NULL, occurred_at DATETIME NOT NULL, "
                "event_type VARCHAR(512) NOT NULL, message TEXT NOT NULL, severity VARCHAR(64), "
                "user_name VARCHAR(512), entity_name VARCHAR(1024), entity_type VARCHAR(256), "
                "vmware_key INTEGER NOT NULL, chain_id INTEGER, notable_score INTEGER NOT NULL, "
                "notable_tags JSON)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO events ("
                "id, vcenter_id, occurred_at, event_type, message, severity, user_name, "
                "entity_name, entity_type, vmware_key, chain_id, notable_score, notable_tags"
                ") SELECT "
                "id, vcenter_id, occurred_at, event_type, message, severity, user_name, "
                "entity_name, entity_type, vmware_key, chain_id, notable_score, notable_tags "
                "FROM events_legacy"
            )
        )
        await conn.execute(text("DROP TABLE events_legacy"))
        await conn.execute(
            text(
                "CREATE TABLE alert_states_legacy AS "
                "SELECT id, rule_id, state, context_key, fired_at, resolved_at FROM alert_states"
            )
        )
        await conn.execute(text("DROP TABLE alert_states"))
        await conn.execute(
            text(
                "CREATE TABLE alert_states ("
                "id INTEGER PRIMARY KEY, rule_id INTEGER NOT NULL, state VARCHAR(32) NOT NULL, "
                "context_key VARCHAR(512) NOT NULL, fired_at DATETIME NOT NULL, "
                "resolved_at DATETIME)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO alert_states "
                "(id, rule_id, state, context_key, fired_at, resolved_at) "
                "SELECT id, rule_id, state, context_key, fired_at, resolved_at FROM alert_states_legacy"
            )
        )
        await conn.execute(text("DROP TABLE alert_states_legacy"))

    await reset_db()
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    bind_settings(get_settings())

    with pytest.raises(LegacySchemaStampError):
        await init_db()


@pytest.mark.asyncio
async def test_alert_history_occurred_at_is_backfilled_from_notified_at(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``occurred_at`` 追加前の行は ``notified_at`` で埋まり、列は NOT NULL でインデックスが付く。"""
    from alembic import command

    from vcenter_event_assistant.db.alembic_runner import _run_with_connection, alembic_config
    from vcenter_event_assistant.db.session import get_engine

    db_path = tmp_path / "occurred.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    bind_settings(get_settings())
    await reset_db()
    await init_db()
    engine = get_engine()
    cfg = alembic_config()

    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: _run_with_connection(c, cfg, lambda cc: command.downgrade(cc, "c0d1e2f3a4b5"))
        )
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO alert_rules (id, name, rule_type, is_enabled, alert_level, config, created_at) "
                "VALUES (1, 'r', 'event_score', 1, 'warning', '{}', '2026-03-22 00:00:00')"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO alert_history (id, rule_id, alert_level, state, context_key, notified_at, "
                "channel, delivery_status) VALUES "
                "(1, 1, 'warning', 'firing', 'X', '2026-03-22 01:02:03.000000', 'none', 'skipped')"
            )
        )
    await init_db()

    async with engine.connect() as conn:
        occurred = (await conn.execute(text("SELECT occurred_at FROM alert_history WHERE id = 1"))).scalar_one()

        def sync_inspect(sync_conn):
            insp = inspect(sync_conn)
            cols = {c["name"]: c for c in insp.get_columns("alert_history")}
            idx = {i["name"]: i["column_names"] for i in insp.get_indexes("alert_history")}
            return cols, idx

        cols, idx = await conn.run_sync(sync_inspect)
    assert str(occurred).startswith("2026-03-22 01:02:03")
    assert cols["occurred_at"]["nullable"] is False
    assert idx["ix_alert_history_occurred_at"] == ["occurred_at"]
    assert idx["ix_alert_history_notified_at"] == ["notified_at"]
    assert await get_applied_alembic_revision(engine) == get_alembic_head()
    await reset_db()
