"""init_db の旧スキーマ向け列追加（create_all では既存テーブルを変更しない）。"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from vcenter_event_assistant.db.session import init_db, reset_db


async def _alert_states_column_names(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as conn:
        result = await conn.execute(text("PRAGMA table_info(alert_states)"))
        return [row[1] for row in result.fetchall()]


@pytest.mark.asyncio
async def test_init_db_adds_alert_states_last_notified_at_on_legacy_schema(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``last_notified_at`` 列が無い旧 ``alert_states`` に対し ``init_db`` で列が追加される。"""
    db_path = tmp_path / "legacy.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    await reset_db()
    await init_db()

    from vcenter_event_assistant.db.session import get_engine

    engine = get_engine()
    cols = await _alert_states_column_names(engine)
    assert "last_notified_at" in cols

    # 旧スキーマ相当: 列を落として再実行
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

    cols_before = await _alert_states_column_names(engine)
    assert "last_notified_at" not in cols_before

    from vcenter_event_assistant.db.session import _ensure_alert_states_last_notified_at_column

    await _ensure_alert_states_last_notified_at_column(engine)

    cols_after = await _alert_states_column_names(engine)
    assert "last_notified_at" in cols_after

    await reset_db()
