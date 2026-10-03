"""Durable delivery: faults must not lose committed alerts or stop later work."""

from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from vcenter_event_assistant.db.models import (
    AlertHistory,
    AlertNotificationOutbox,
    AlertRule,
    AlertState,
    MetricSample,
    VCenter,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alerting.alert_eval import AlertEvaluator
from vcenter_event_assistant.settings import get_settings
from vcenter_event_assistant.services.alerting import notification_outbox as outbox
from vcenter_event_assistant.services.alerting.notification.email_channel import (
    EmailChannel,
)
from vcenter_event_assistant.services.alerting.notification.delivery_outcome import (
    NotificationDeliveryOutcome,
)


@pytest.fixture
def settings():
    return get_settings().model_copy(
        update={"smtp_host": "smtp.test", "alert_email_to": "ops@example.com"}
    )


@pytest.fixture
def clock(monkeypatch):
    now = [datetime.now(timezone.utc)]
    monkeypatch.setattr(outbox, "utc_now", lambda: now[0])
    return now


async def rows():
    async with session_scope() as session:
        return (
            list(
                (
                    await session.scalars(
                        select(AlertHistory).order_by(AlertHistory.id)
                    )
                ).all()
            ),
            list((await session.scalars(select(AlertNotificationOutbox))).all()),
        )


async def queue(settings, count=1):
    ids = await seed_metric_rules(count)
    await AlertEvaluator(settings).evaluate_all()
    return ids


async def seed_metric_rules(count=1):
    async with session_scope() as session:
        vc = VCenter(name="outbox-vc", host="outbox-vc", username="u", password="p")
        session.add(vc)
        await session.flush()
        rules = [
            AlertRule(
                name=f"CPU {i}",
                rule_type="metric_threshold",
                config={"metric_key": "cpu", "threshold": 90},
            )
            for i in range(count)
        ]
        session.add_all(rules)
        session.add(
            MetricSample(
                vcenter_id=vc.id,
                sampled_at=datetime.now(timezone.utc),
                entity_type="HostSystem",
                entity_moid="host-1",
                entity_name="host",
                metric_key="cpu",
                value=95,
            )
        )
        await session.flush()
        return [rule.id for rule in rules]


@pytest.mark.asyncio
async def test_enqueue_error_rolls_back_rule_but_does_not_stop_later_rules(settings):
    ids = await seed_metric_rules(2)
    evaluator = AlertEvaluator(settings)
    original = evaluator._enqueue_notification

    async def fail_first(pending, session):
        await original(pending, session)
        if pending.rule_id == ids[0]:
            raise RuntimeError("DB commit failed")

    with patch.object(evaluator, "_enqueue_notification", side_effect=fail_first):
        summary = await evaluator.evaluate_all()
    assert summary.firings == 1
    async with session_scope() as session:
        assert [
            state.rule_id for state in (await session.scalars(select(AlertState))).all()
        ] == [ids[1]]
    histories, intents = await rows()
    assert len(histories) == len(intents) == 1
    assert histories[0].rule_id == ids[1]


@pytest.mark.asyncio
async def test_snapshot_database_error_does_not_prevent_delivery(settings):
    await queue(settings)
    with (
        patch.object(
            outbox,
            "persist_alert_rule_firing_snapshot",
            new=AsyncMock(side_effect=RuntimeError("snapshot DB down")),
        ),
        patch.object(
            EmailChannel,
            "notify",
            new=AsyncMock(return_value=NotificationDeliveryOutcome("email", True)),
        ) as send,
    ):
        summary = await outbox.deliver_notifications(settings)
    assert send.await_count == 1
    assert summary.succeeded == 1
    histories, intents = await rows()
    assert not intents and histories[0].success is True


@pytest.mark.asyncio
async def test_evaluation_never_waits_for_smtp(settings):
    with patch.object(
        EmailChannel,
        "notify",
        new=AsyncMock(side_effect=AssertionError("SMTP during evaluation")),
    ):
        await queue(settings)
    histories, intents = await rows()
    assert len(histories) == len(intents) == 1
    assert histories[0].delivery_status == "pending"
    assert histories[0].attempt_count == 0


@pytest.mark.asyncio
async def test_retry_backoff_then_success_uses_same_history(settings, clock):
    await queue(settings)
    snapshot = AsyncMock()
    send = AsyncMock(
        side_effect=[
            TimeoutError("smtp timeout"),
            TimeoutError("again"),
            NotificationDeliveryOutcome("email", True),
        ]
    )
    with (
        patch.object(outbox, "persist_alert_rule_firing_snapshot", new=snapshot),
        patch.object(EmailChannel, "notify", new=send),
    ):
        first = await outbox.deliver_notifications(settings)
        assert first.retrying == 1
        histories, intents = await rows()
        assert histories[0].success is False and histories[0].attempt_count == 1
        assert outbox.as_utc(intents[0].next_attempt_at) == clock[0] + timedelta(
            seconds=60
        )
        await outbox.deliver_notifications(settings)
        assert send.await_count == 1
        clock[0] += timedelta(seconds=60)
        await outbox.deliver_notifications(settings)
        histories, intents = await rows()
        assert outbox.as_utc(intents[0].next_attempt_at) == clock[0] + timedelta(
            seconds=120
        )
        clock[0] += timedelta(seconds=120)
        final = await outbox.deliver_notifications(settings)
    assert final.succeeded == 1 and snapshot.await_count == 1
    histories, intents = await rows()
    assert len(histories) == 1 and not intents
    assert histories[0].attempt_count == 3 and histories[0].error_message is None


@pytest.mark.asyncio
async def test_deadline_expires_even_before_next_attempt(settings, clock):
    await queue(settings)
    clock[0] += timedelta(hours=24)
    with patch.object(EmailChannel, "notify", new=AsyncMock()) as send:
        summary = await outbox.deliver_notifications(settings)
    assert summary.failed == 1 and send.await_count == 0
    histories, intents = await rows()
    assert not intents and histories[0].delivery_status == "failed"
    assert "deadline" in histories[0].error_message


@pytest.mark.asyncio
async def test_authentication_failure_retries_after_credentials_fix(settings, clock):
    import smtplib

    await queue(settings)
    with patch.object(
        EmailChannel,
        "notify",
        new=AsyncMock(side_effect=smtplib.SMTPAuthenticationError(535, b"bad auth")),
    ):
        assert (await outbox.deliver_notifications(settings)).retrying == 1
    settings.smtp_password = "new-password"
    clock[0] += timedelta(seconds=60)
    with patch.object(
        EmailChannel,
        "notify",
        new=AsyncMock(return_value=NotificationDeliveryOutcome("email", True)),
    ):
        assert (await outbox.deliver_notifications(settings)).succeeded == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["smtp_host", "alert_email_to"])
async def test_missing_configuration_is_skipped_without_queue(settings, missing):
    setattr(settings, missing, None)
    await queue(settings)
    histories, intents = await rows()
    assert not intents and histories[0].delivery_status == "skipped"
    assert histories[0].success is None and histories[0].attempt_count == 0


@pytest.mark.asyncio
async def test_configuration_removed_after_enqueue_skips(settings):
    await queue(settings)
    settings.smtp_host = None
    with patch("smtplib.SMTP") as smtp:
        assert (await outbox.deliver_notifications(settings)).skipped == 1
    smtp.assert_not_called()
    histories, intents = await rows()
    assert not intents and histories[0].success is None


@pytest.mark.asyncio
async def test_render_error_records_failure_without_retry(settings):
    with patch.object(
        outbox.NotificationRenderer, "render", side_effect=ValueError("broken template")
    ):
        await queue(settings)
    histories, intents = await rows()
    assert not intents and histories[0].delivery_status == "failed"
    assert (
        histories[0].attempt_count == 0
        and "broken template" in histories[0].error_message
    )
    async with session_scope() as session:
        assert len((await session.scalars(select(AlertState))).all()) == 1


@pytest.mark.asyncio
async def test_immutable_envelope_message_id_and_current_connection(settings, clock):
    ids = await queue(settings)
    histories, intents = await rows()
    original = intents[0]
    captured = []

    def smtp_send(current_settings, message):
        captured.append((current_settings.smtp_host, message))
        if len(captured) == 1:
            raise TimeoutError("accepted but acknowledgement lost")

    with patch(
        "vcenter_event_assistant.services.alerting.notification.email_channel._send_smtp_message",
        side_effect=smtp_send,
    ):
        await outbox.deliver_notifications(settings)
        settings.smtp_host = "replacement.smtp"
        settings.alert_email_to = "changed@example.com"
        settings.alert_email_from = "changed-sender@example.com"
        async with session_scope() as session:
            rule = await session.get(AlertRule, ids[0])
            rule.name = "renamed"
            rule.is_enabled = False
            state = (await session.scalars(select(AlertState))).one()
            state.state = "resolved"
        clock[0] += timedelta(seconds=60)
        await outbox.deliver_notifications(settings)
    assert len(captured) == 2
    assert captured[1][0] == "replacement.smtp"
    for _, message in captured:
        assert message["Message-ID"] == original.message_id
        assert message["To"] == original.to_address
        assert message["From"] == original.from_address
        assert message["Subject"] == original.subject
        assert message.get_content().rstrip() == original.body.rstrip()


@pytest.mark.asyncio
async def test_result_commit_failure_leaves_restart_safe_intent(
    settings, clock, monkeypatch
):
    await queue(settings)
    original_scope = outbox.session_scope
    fail = [True]

    @asynccontextmanager
    async def failing_scope(*args, **kwargs):
        async with original_scope(*args, **kwargs) as session:
            yield session
            if fail[0] and any(
                isinstance(row, AlertHistory) and row.delivery_status == "succeeded"
                for row in session.dirty
            ):
                fail[0] = False
                raise RuntimeError("result commit unavailable")

    monkeypatch.setattr(outbox, "session_scope", failing_scope)
    send = AsyncMock(return_value=NotificationDeliveryOutcome("email", True))
    with patch.object(EmailChannel, "notify", new=send):
        await outbox.deliver_notifications(settings)
        histories, intents = await rows()
        assert len(intents) == 1 and histories[0].attempt_count == 1
        assert histories[0].delivery_status == "pending"
        clock[0] += timedelta(seconds=60)
        await outbox.deliver_notifications(settings)
    histories, intents = await rows()
    assert not intents and histories[0].attempt_count == 2
    assert send.await_count == 2


@pytest.mark.asyncio
async def test_batch_continues_after_delivery_database_error(settings):
    await queue(settings, 2)
    original = outbox._deliver_one

    async def fail_first(history_id, settings):
        if history_id == 1:
            raise RuntimeError("delivery DB error")
        return await original(history_id, settings)

    with (
        patch.object(outbox, "_deliver_one", side_effect=fail_first),
        patch.object(
            EmailChannel,
            "notify",
            new=AsyncMock(return_value=NotificationDeliveryOutcome("email", True)),
        ),
    ):
        summary = await outbox.deliver_notifications(settings)
    assert summary.succeeded == 1
    histories, intents = await rows()
    assert len(intents) == 1 and histories[1].delivery_status == "succeeded"


@pytest.mark.asyncio
async def test_batch_limit_and_no_duplicate_concurrent_dispatch(settings):
    settings.alert_delivery_batch_size = 1
    await queue(settings, 2)
    started, release = asyncio.Event(), asyncio.Event()

    async def slow_send(*args, **kwargs):
        started.set()
        await release.wait()
        return NotificationDeliveryOutcome("email", True)

    with patch.object(EmailChannel, "notify", side_effect=slow_send) as send:
        running = asyncio.create_task(outbox.deliver_notifications(settings))
        await started.wait()
        other = await outbox.deliver_notifications(settings)
        assert other.succeeded == 0 and send.await_count == 1
        release.set()
        assert (await running).succeeded == 1
    assert len((await rows())[1]) == 1


@pytest.mark.asyncio
async def test_cancellation_waits_for_inflight_send_and_propagates(settings):
    await queue(settings)
    started, release = asyncio.Event(), asyncio.Event()

    async def slow_send(*args, **kwargs):
        started.set()
        await release.wait()
        return NotificationDeliveryOutcome("email", True)

    with patch.object(EmailChannel, "notify", side_effect=slow_send):
        running = asyncio.create_task(outbox.deliver_notifications(settings))
        await started.wait()
        running.cancel()
        await asyncio.sleep(0)
        assert outbox._delivery_lock.locked()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await running
    assert not outbox._delivery_lock.locked()
    histories, intents = await rows()
    assert not intents and histories[0].delivery_status == "succeeded"


@pytest.mark.asyncio
async def test_queued_history_and_rule_deletion_cascade(settings, client):
    ids = await queue(settings, 2)
    histories, _ = await rows()
    assert (
        await client.delete(f"/api/alerts/history/{histories[0].id}")
    ).status_code == 204
    assert (await client.delete(f"/api/alerts/rules/{ids[1]}")).status_code == 204
    assert not (await rows())[1]


@pytest.mark.asyncio
async def test_retention_preserves_pending_and_retrying(settings, clock):
    from vcenter_event_assistant.services.ingestion import purge_old_alert_history

    await queue(settings, 2)
    settings.alert_history_retention_days = 1
    async with session_scope() as session:
        histories = (
            await session.scalars(select(AlertHistory).order_by(AlertHistory.id))
        ).all()
        for row in histories:
            row.notified_at = clock[0] - timedelta(days=10)
        histories[1].delivery_status = "retrying"
        assert await purge_old_alert_history(session, settings=settings) == 0
    assert len((await rows())[1]) == 2


@pytest.mark.asyncio
async def test_history_api_returns_delivery_status_and_attempts(settings, client):
    await queue(settings)
    item = (await client.get("/api/alerts/history")).json()["items"][0]
    assert item["delivery_status"] == "pending" and item["attempt_count"] == 0
    assert item["next_attempt_at"] is not None and item["last_attempt_at"] is None


@pytest.mark.asyncio
async def test_restart_resumes_file_backed_queue(settings, tmp_path):
    from vcenter_event_assistant.db.session import init_db, reset_db

    settings.database_url = f"sqlite+aiosqlite:///{tmp_path / 'restart.db'}"
    await reset_db()
    await init_db(settings=settings)
    await queue(settings)
    await reset_db()
    await init_db(settings=settings)
    with patch.object(
        EmailChannel,
        "notify",
        new=AsyncMock(return_value=NotificationDeliveryOutcome("email", True)),
    ):
        assert (await outbox.deliver_notifications(settings)).succeeded == 1
    assert not (await rows())[1]


@pytest.mark.asyncio
async def test_snapshot_sql_error_is_rolled_back_before_smtp(settings):
    from sqlalchemy import text

    await queue(settings)

    async def broken_snapshot(*, session, **kwargs):
        await session.execute(text("SELECT * FROM missing_snapshot_table"))

    with (
        patch.object(
            outbox, "persist_alert_rule_firing_snapshot", side_effect=broken_snapshot
        ),
        patch.object(
            EmailChannel,
            "notify",
            new=AsyncMock(return_value=NotificationDeliveryOutcome("email", True)),
        ),
    ):
        assert (await outbox.deliver_notifications(settings)).succeeded == 1
    assert not (await rows())[1]


@pytest.mark.asyncio
async def test_mock_intent_never_uses_smtp_after_mode_changes(settings):
    settings.mock_mode = True
    await queue(settings)
    settings.mock_mode = False
    with patch("smtplib.SMTP") as smtp:
        assert (await outbox.deliver_notifications(settings)).succeeded == 1
        smtp.assert_not_called()
    histories, _ = await rows()
    assert histories[0].channel == "mock"


@pytest.mark.asyncio
async def test_real_intent_is_skipped_when_mock_mode_enabled(settings):
    await queue(settings)
    settings.mock_mode = True
    with patch("smtplib.SMTP") as smtp:
        assert (await outbox.deliver_notifications(settings)).skipped == 1
        smtp.assert_not_called()


def test_backoff_caps_even_after_many_attempts(settings):
    assert outbox.retry_delay(settings, 1) == 60
    assert outbox.retry_delay(settings, 2) == 120
    assert outbox.retry_delay(settings, 7) == 3600
    assert outbox.retry_delay(settings, 1000000) == 3600
