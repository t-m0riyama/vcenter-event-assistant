"""Migration and delivery against SQLite and an explicitly dedicated PostgreSQL DB."""

import os
from unittest.mock import AsyncMock, patch

import pytest
from alembic import command
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from vcenter_event_assistant.db.alembic_runner import (
    _run_with_connection,
    alembic_config,
)
from vcenter_event_assistant.db.models import (
    AlertHistory,
    AlertNotificationOutbox,
    AlertRule,
    AlertState,
)
from vcenter_event_assistant.db.session import init_db, reset_db, session_scope
from vcenter_event_assistant.services.alerting.alert_eval import AlertEvaluator
from vcenter_event_assistant.services.alerting.alert_eval_common import (
    PendingAlertNotification,
)
from vcenter_event_assistant.services.alerting import notification_outbox as outbox
from vcenter_event_assistant.services.alerting.notification.email_channel import (
    EmailChannel,
)
from vcenter_event_assistant.services.alerting.notification.delivery_outcome import (
    NotificationDeliveryOutcome,
)
from vcenter_event_assistant.services.alerting.notification_outbox import (
    deliver_notifications,
    utc_now,
)
from vcenter_event_assistant.settings import get_settings


@pytest.fixture(params=["sqlite", "postgres"])
async def database(request, tmp_path):
    if request.param == "postgres":
        url = os.environ.get("VEA_TEST_POSTGRES_URL")
        if not url:
            pytest.skip(
                "VEA_TEST_POSTGRES_URL must point to a dedicated test DB (schema is cleared)"
            )
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"
    settings = get_settings().model_copy(
        update={
            "database_url": url,
            "smtp_host": "smtp.test",
            "alert_email_to": "ops@example.com",
        }
    )
    await reset_db()
    engine = create_async_engine(url)
    if request.param == "postgres":
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    try:
        yield settings, engine
    finally:
        await reset_db()
        await engine.dispose()


async def migrate(engine, settings, revision):
    cfg = alembic_config(settings=settings)
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync: _run_with_connection(
                sync, cfg, lambda cfg: command.upgrade(cfg, revision)
            )
        )


@pytest.mark.asyncio
async def test_migration_maps_legacy_results_without_replaying(database):
    settings, engine = database
    await migrate(engine, settings, "x5y6z7a8b9c0")
    async with engine.begin() as connection:
        await connection.execute(
            text("""INSERT INTO alert_rules
            (id, name, rule_type, is_enabled, config, created_at, alert_level)
            VALUES (1, 'legacy', 'metric_threshold', true, '{}', CURRENT_TIMESTAMP, 'warning')""")
        )
        for index, success in enumerate((True, False, None), 1):
            await connection.execute(
                text("""INSERT INTO alert_history
                (id, rule_id, alert_level, state, context_key, notified_at, channel, success)
                VALUES (:id, 1, 'warning', 'firing', 'host', CURRENT_TIMESTAMP, 'email', :success)"""),
                {"id": index, "success": success},
            )
    await migrate(engine, settings, "head")
    async with session_scope(settings=settings) as session:
        rows = list(
            (
                await session.scalars(select(AlertHistory).order_by(AlertHistory.id))
            ).all()
        )
        assert [row.delivery_status for row in rows] == [
            "succeeded",
            "failed",
            "skipped",
        ]
        assert all(
            row.attempt_count is None and row.next_attempt_at is None for row in rows
        )
        assert not (await session.scalars(select(AlertNotificationOutbox))).all()


@pytest.mark.asyncio
async def test_delivery_and_state_transaction_on_both_databases(database, monkeypatch):
    settings, _ = database
    await init_db(settings=settings)
    now = utc_now()
    async with session_scope(settings=settings) as session:
        rule = AlertRule(
            name="DB integration", rule_type="event_score", config={"threshold": 60}
        )
        session.add(rule)
        await session.flush()
        rule_id = rule.id
        session.add(
            AlertState(
                rule_id=rule_id, state="firing", context_key="HostLost", fired_at=now
            )
        )

    evaluator = AlertEvaluator(settings)
    original = evaluator._enqueue_notification

    async def fail_commit(pending, session):
        await original(pending, session)
        await session.flush()
        raise RuntimeError("intent commit unavailable")

    with patch.object(evaluator, "_enqueue_notification", side_effect=fail_commit):
        with pytest.raises(RuntimeError):
            await evaluator.resolve_event_score_manually(rule_id, "HostLost")
    async with session_scope(settings=settings) as session:
        assert (await session.scalars(select(AlertState))).one().state == "firing"
        assert not (await session.scalars(select(AlertHistory))).all()
        assert not (await session.scalars(select(AlertNotificationOutbox))).all()
    await evaluator.resolve_event_score_manually(rule_id, "HostLost")
    await reset_db()  # New engine/session simulates restart before dispatch.
    async with session_scope(settings=settings) as session:
        state = (await session.scalars(select(AlertState))).one()
        assert state.state == "resolved"
        assert len((await session.scalars(select(AlertNotificationOutbox))).all()) == 1
    clock = [utc_now()]
    monkeypatch.setattr(outbox, "utc_now", lambda: clock[0])
    with patch.object(
        EmailChannel,
        "notify",
        new=AsyncMock(side_effect=TimeoutError("SMTP unavailable")),
    ):
        assert (await deliver_notifications(settings)).retrying == 1
    await reset_db()
    from datetime import timedelta

    clock[0] += timedelta(seconds=60)
    with patch.object(
        EmailChannel,
        "notify",
        new=AsyncMock(return_value=NotificationDeliveryOutcome("email", True)),
    ):
        assert (await deliver_notifications(settings)).succeeded == 1
    async with session_scope(settings=settings) as session:
        assert not (await session.scalars(select(AlertNotificationOutbox))).all()
        history = (await session.scalars(select(AlertHistory))).one()
        assert history.delivery_status == "succeeded" and history.attempt_count == 2


@pytest.mark.asyncio
async def test_replayed_migration_preserves_pending_intents(database):
    settings, engine = database
    await init_db(settings=settings)
    now = utc_now()
    async with session_scope(settings=settings) as session:
        rule = AlertRule(name="preserve intents", rule_type="event_score", config={})
        session.add(rule)
        await session.flush()
        pending = PendingAlertNotification(
            rule.id,
            rule.name,
            rule.rule_type,
            "warning",
            "resolved",
            "event",
            now,
            now,
            {},
        )
        await outbox.enqueue_notification(session, settings, pending)
        await outbox.enqueue_notification(session, settings, pending)
        await session.flush()
        histories = list(
            (
                await session.scalars(select(AlertHistory).order_by(AlertHistory.id))
            ).all()
        )
        histories[1].delivery_status = "retrying"
        histories[1].success = False
        histories[1].attempt_count = 1
    cfg = alembic_config(settings=settings)
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync: _run_with_connection(
                sync, cfg, lambda cfg: command.stamp(cfg, "x5y6z7a8b9c0")
            )
        )
    await migrate(engine, settings, "head")
    async with session_scope(settings=settings) as session:
        histories = list(
            (
                await session.scalars(select(AlertHistory).order_by(AlertHistory.id))
            ).all()
        )
        assert [row.delivery_status for row in histories] == ["pending", "retrying"]
        assert len((await session.scalars(select(AlertNotificationOutbox))).all()) == 2
