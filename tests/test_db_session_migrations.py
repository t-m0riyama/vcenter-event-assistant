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
    """``occurred_at`` 追加前の行は ``notified_at`` で埋まり、列は NOT NULL でインデックスが付く。

    alert_notification_outbox は alert_history を ON DELETE CASCADE で参照するので、SQLite で表を
    作り直すと配信待ちの通知が消える。upgrade・downgrade のどちらでも残ることを確かめる。
    """
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
        # 配信待ちの通知。alert_history を作り直すと ON DELETE CASCADE で消えるおそれがある
        await conn.execute(
            text(
                "INSERT INTO alert_notification_outbox (history_id, subject, body, from_address, "
                "to_address, message_id, notification, created_at, expires_at, next_attempt_at) VALUES "
                "(1, 's', 'b', 'f@example.com', 't@example.com', '<m@x>', '{}', "
                "'2026-03-22 01:02:03', '2026-03-23 01:02:03', '2026-03-22 01:02:03')"
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
    async with engine.connect() as conn:
        pending = (await conn.execute(text("SELECT count(*) FROM alert_notification_outbox"))).scalar_one()
    assert pending == 1
    assert cols["occurred_at"]["nullable"] is False
    assert idx["ix_alert_history_occurred_at"] == ["occurred_at"]
    assert idx["ix_alert_history_notified_at"] == ["notified_at"]
    assert await get_applied_alembic_revision(engine) == get_alembic_head()

    # downgrade でも表を作り直さない（配信待ちの通知が残り、列だけが消える）
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: _run_with_connection(c, cfg, lambda cc: command.downgrade(cc, "c0d1e2f3a4b5"))
        )
    async with engine.connect() as conn:
        pending = (await conn.execute(text("SELECT count(*) FROM alert_notification_outbox"))).scalar_one()
        cols_after = await conn.run_sync(
            lambda c: {col["name"] for col in inspect(c).get_columns("alert_history")}
        )
    assert pending == 1
    assert "occurred_at" not in cols_after
    await reset_db()


@pytest.mark.asyncio
async def test_snapshot_result_columns_are_added_without_rebuilding_the_table(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``view_request_payload`` / ``result_payload`` は NULL 可の列として足され、既存の行はそのまま残る。"""
    from alembic import command

    from vcenter_event_assistant.db.alembic_runner import _run_with_connection, alembic_config
    from vcenter_event_assistant.db.session import get_engine

    db_path = tmp_path / "snapshot_result.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    bind_settings(get_settings())
    await reset_db()
    await init_db()
    engine = get_engine()
    cfg = alembic_config()

    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: _run_with_connection(c, cfg, lambda cc: command.downgrade(cc, "f3a4b5c6d7e8"))
        )
    async with engine.connect() as conn:
        cols_before = await conn.run_sync(
            lambda c: {col["name"] for col in inspect(c).get_columns("incident_timeline_manual_snapshots")}
        )
    assert "result_payload" not in cols_before
    assert "view_request_payload" not in cols_before

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO incident_timeline_manual_snapshots "
                "(id, from_time, to_time, timestamp_utc, operator_note, build_request_payload, "
                "snapshot_kind, created_at) VALUES "
                "('00000000000000000000000000000001', '2026-03-22 00:00:00', '2026-03-22 01:00:00', "
                "'2026-03-22 02:00:00', 'old', '{}', 'manual', '2026-03-22 02:00:00')"
            )
        )
    await init_db()

    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda c: {col["name"]: col for col in inspect(c).get_columns("incident_timeline_manual_snapshots")}
        )
        row = (
            await conn.execute(
                text("SELECT operator_note, result_payload, view_request_payload FROM incident_timeline_manual_snapshots")
            )
        ).one()
    assert cols["result_payload"]["nullable"] is True
    assert cols["view_request_payload"]["nullable"] is True
    assert tuple(row) == ("old", None, None)
    assert await get_applied_alembic_revision(engine) == get_alembic_head()
    await reset_db()


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_event_entities_migration_round_trip(tmp_path, backend) -> None:
    """対象を保存する移行は既存イベントを残し、元に戻して再適用できる。"""
    import os
    from uuid import uuid4

    from alembic import command
    from sqlalchemy import Uuid, bindparam
    from sqlalchemy.ext.asyncio import create_async_engine

    from vcenter_event_assistant.db.alembic_runner import _run_with_connection, alembic_config

    if backend == "postgres":
        url = os.environ.get("VEA_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("VEA_TEST_POSTGRES_URL must point to a dedicated test DB")
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'event_entities.db'}"
    settings = get_settings().model_copy(update={"database_url": url})
    cfg = alembic_config(settings=settings)
    engine = create_async_engine(url)
    vcenter_id = uuid4()

    def check_old_schema(sync_conn) -> None:
        inspector = inspect(sync_conn)
        assert not inspector.has_table("event_entities")
        assert "entity_moid" not in {c["name"] for c in inspector.get_columns("events")}
        assert "ix_events_vcenter_id_entity_moid" not in {
            i["name"] for i in inspector.get_indexes("events")
        }

    def check_new_schema(sync_conn) -> None:
        inspector = inspect(sync_conn)
        columns = {c["name"]: c for c in inspector.get_columns("events")}
        assert columns["entity_moid"]["nullable"] is True
        assert columns["entity_moid"]["type"].length == 256
        indexes = {i["name"]: i["column_names"] for i in inspector.get_indexes("events")}
        assert indexes["ix_events_vcenter_id_entity_moid"] == ["vcenter_id", "entity_moid"]
        indexes = {
            i["name"]: i["column_names"] for i in inspector.get_indexes("event_entities")
            if not i.get("duplicates_constraint")
        }
        assert indexes == {"ix_event_entities_vcenter_id_entity_moid": ["vcenter_id", "entity_moid"]}
        keys = inspector.get_foreign_keys("event_entities")
        assert len(keys) == 1 and keys[0]["referred_table"] == "events"
        assert keys[0]["options"]["ondelete"] == "CASCADE"
        constraints = inspector.get_unique_constraints("event_entities")
        assert {c["name"]: c["column_names"] for c in constraints} == {
            "uq_event_entities_event_id_role_position": ["event_id", "role", "position"]
        }

    def upgrade(sync_conn) -> None:
        _run_with_connection(sync_conn, cfg, lambda cc: command.upgrade(cc, "head"))

    def downgrade(sync_conn) -> None:
        _run_with_connection(sync_conn, cfg, lambda cc: command.downgrade(cc, "d7e8f9a0b1c2"))
        check_old_schema(sync_conn)

    try:
        async with engine.connect() as conn:
            async with conn.begin() as transaction:
                if backend == "postgres":
                    # CI 内の他のテストと DB を共有するため、この試験用のスキーマを使う。
                    schema = f"event_entities_{vcenter_id.hex}"
                    await conn.execute(text(f"CREATE SCHEMA {schema}"))
                    await conn.execute(text(f"SET LOCAL search_path TO {schema}"))

                await conn.run_sync(upgrade)
                await conn.run_sync(downgrade)
                await conn.execute(
                    text("""INSERT INTO vcenters
                        (id, name, host, protocol, port, username, password, verify_ssl, is_enabled, created_at)
                        VALUES (:id, 'legacy', 'vc.example', 'https', 443, 'u', 'p', true, true, CURRENT_TIMESTAMP)""")
                    .bindparams(bindparam("id", type_=Uuid())),
                    {"id": vcenter_id},
                )
                await conn.execute(
                    text("""INSERT INTO events
                        (vcenter_id, collector_id, occurred_at, event_type, message, vmware_key, notable_score)
                        VALUES (:id, 'builtin.vcenter.events', CURRENT_TIMESTAMP, 'legacy', 'old', 11, 0)""")
                    .bindparams(bindparam("id", type_=Uuid())),
                    {"id": vcenter_id},
                )

                for _ in range(2):
                    await conn.run_sync(upgrade)
                    await conn.run_sync(check_new_schema)
                    rows = await conn.execute(text("SELECT message, entity_moid FROM events"))
                    assert rows.all() == [("old", None)]
                    assert await conn.scalar(text("SELECT count(*) FROM event_entities")) == 0
                    assert await get_applied_alembic_revision(conn) == get_alembic_head(settings=settings)
                    await conn.run_sync(downgrade)

                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_disk_usage_metric_key_is_renamed_in_samples_rules_and_snapshots(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``host.disk.usage_pct`` は ``host.disk.usage_kbps`` に付け替わり、downgrade で元に戻る（Issue #316）。"""
    import json
    import uuid
    from datetime import datetime, timezone

    from alembic import command
    from sqlalchemy import select

    from vcenter_event_assistant.db.alembic_runner import _run_with_connection, alembic_config
    from vcenter_event_assistant.db.models import (
        AlertRule,
        IncidentTimelineManualSnapshot,
        MetricSample,
        VCenter,
    )
    from vcenter_event_assistant.db.session import get_engine, session_scope

    old_key = "host.disk.usage_pct"
    new_key = "host.disk.usage_kbps"
    previous_revision = "a4b5c6d7e8f9"

    db_path = tmp_path / "rename_disk_usage.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    bind_settings(get_settings())
    await reset_db()
    await init_db()
    engine = get_engine()
    cfg = alembic_config()

    async def downgrade() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: _run_with_connection(c, cfg, lambda cc: command.downgrade(cc, previous_revision))
            )

    async def read_state() -> tuple[list[tuple[str, str, float]], dict[str, dict], dict[str, dict | None]]:
        async with session_scope() as session:
            samples = [
                (row.entity_moid, row.metric_key, row.value)
                for row in (
                    await session.execute(select(MetricSample).order_by(MetricSample.entity_moid, MetricSample.metric_key))
                ).scalars()
            ]
            rules = dict((await session.execute(select(AlertRule.name, AlertRule.config))).all())
            snapshots = {
                row.operator_note: row.graph_context
                for row in (await session.execute(select(IncidentTimelineManualSnapshot))).scalars()
            }
        return samples, rules, snapshots

    await downgrade()

    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    vc_id = uuid.uuid4()

    def sample(moid: str, key: str, value: float) -> MetricSample:
        return MetricSample(
            vcenter_id=vc_id,
            sampled_at=t0,
            entity_type="HostSystem",
            entity_moid=moid,
            entity_name=moid,
            metric_key=key,
            value=value,
        )

    def snapshot(note: str, graph_context: dict | None) -> IncidentTimelineManualSnapshot:
        row = IncidentTimelineManualSnapshot(
            from_time=t0, to_time=t0, timestamp_utc=t0, operator_note=note, build_request_payload={}
        )
        if graph_context is not None:
            row.graph_context = graph_context
        return row

    async with session_scope() as session:
        session.add(VCenter(id=vc_id, name="vc", host="vc.example.local", username="u", password="p"))
        await session.flush()
        session.add_all(
            [
                sample("host-1", old_key, 1200.0),
                # 新しい名前の行がすでにある点（新しいコードが先に書いた場合）。古い行は一意制約でぶつかる。
                sample("host-2", old_key, 10.0),
                sample("host-2", new_key, 20.0),
                sample("host-3", "host.disk.read_kbps", 5.0),
                snapshot("disk", {"metric_key": old_key, "chart_event_type": "vim.event.X"}),
                snapshot("cpu", {"metric_key": "host.cpu.usage_pct"}),
                snapshot("none", None),
            ]
        )
        await session.execute(
            text(
                "INSERT INTO alert_rules (name, rule_type, is_enabled, alert_level, config, created_at) "
                "VALUES (:name, :rule_type, 1, 'warning', :config, CURRENT_TIMESTAMP)"
            ),
            [
                {"name": "disk", "rule_type": "metric_threshold", "config": json.dumps({"metric_key": old_key, "threshold": 5000})},
                {"name": "cpu", "rule_type": "metric_threshold", "config": json.dumps({"metric_key": "host.cpu.usage_pct", "threshold": 90})},
                {"name": "score", "rule_type": "event_score", "config": json.dumps({"threshold": 60})},
            ],
        )

    await init_db()
    assert await get_applied_alembic_revision(engine) == get_alembic_head()

    samples, rules, snapshots = await read_state()
    assert samples == [
        ("host-1", new_key, 1200.0),
        ("host-2", new_key, 20.0),
        ("host-3", "host.disk.read_kbps", 5.0),
    ]
    assert rules == {
        "disk": {"metric_key": new_key, "threshold": 5000},
        "cpu": {"metric_key": "host.cpu.usage_pct", "threshold": 90},
        "score": {"threshold": 60},
    }
    assert snapshots == {
        "disk": {"metric_key": new_key, "chart_event_type": "vim.event.X"},
        "cpu": {"metric_key": "host.cpu.usage_pct"},
        "none": None,
    }

    await downgrade()
    samples, rules, snapshots = await read_state()
    assert [key for _moid, key, _value in samples] == [old_key, old_key, "host.disk.read_kbps"]
    assert rules["disk"] == {"metric_key": old_key, "threshold": 5000}
    assert snapshots["disk"] == {"metric_key": old_key, "chart_event_type": "vim.event.X"}

    await init_db()
    await reset_db()
