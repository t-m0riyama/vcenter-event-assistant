"""Transactional notification intents and single-process, restart-safe SMTP retries."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import make_msgid
from email.message import EmailMessage

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.alert_levels import alert_level_label_ja
from vcenter_event_assistant.db.models import (
    AlertHistory,
    AlertNotificationOutbox,
    AlertRule,
    AlertState,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alerting.alert_eval_common import (
    PendingAlertNotification,
    as_utc,
)
from vcenter_event_assistant.services.alerting.notification.channel_factory import (
    build_notification_channel,
)
from vcenter_event_assistant.services.alerting.notification.delivery_outcome import (
    NotificationDeliveryOutcome,
)
from vcenter_event_assistant.services.alerting.notification.renderer import (
    NotificationRenderer,
)
from vcenter_event_assistant.services.incident_timeline_snapshot import (
    persist_alert_rule_firing_snapshot,
)
from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)
_delivery_lock = asyncio.Lock()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def notification_models(
    pending: PendingAlertNotification,
) -> tuple[AlertRule, AlertState]:
    return (
        AlertRule(
            id=pending.rule_id,
            name=pending.rule_name,
            rule_type=pending.rule_type,
            alert_level=pending.alert_level,
        ),
        AlertState(
            rule_id=pending.rule_id,
            state=pending.state,
            context_key=pending.context_key,
            fired_at=pending.fired_at,
            resolved_at=pending.resolved_at,
        ),
    )


async def save_snapshot(
    session: AsyncSession,
    pending: PendingAlertNotification,
    settings: Settings,
    to_time: datetime,
) -> None:
    """A snapshot failure must neither poison its transaction nor prevent delivery."""
    if pending.state != "firing":
        return
    rule, state = notification_models(pending)
    try:
        async with session.begin_nested():
            await persist_alert_rule_firing_snapshot(
                session=session,
                rule=rule,
                state=state,
                details=str(pending.extra_context.get("details", "")),
                to_time=to_time,
                lookback_hours=settings.alert_snapshot_lookback_hours,
            )
    except Exception:
        logger.exception(
            "Alert snapshot failed rule_id=%s context_key=%s state=%s",
            pending.rule_id,
            pending.context_key,
            pending.state,
        )


async def enqueue_notification(
    session: AsyncSession, settings: Settings, pending: PendingAlertNotification
) -> None:
    """Called inside the same transaction as the alert state change."""
    now = utc_now()
    history = AlertHistory(
        rule_id=pending.rule_id,
        alert_level=pending.alert_level,
        state=pending.state,
        context_key=pending.context_key,
        notified_at=now,
        channel="mock" if settings.mock_mode else "email",
        success=None,
        delivery_status="pending",
        attempt_count=0,
        next_attempt_at=now,
    )
    session.add(history)
    if not settings.mock_mode and (
        not settings.smtp_host or not settings.alert_email_to
    ):
        missing = "SMTP_HOST" if not settings.smtp_host else "ALERT_EMAIL_TO"
        history.channel = "none"
        history.delivery_status = "skipped"
        history.next_attempt_at = None
        history.error_message = f"smtp not configured: {missing} is not set"
        logger.warning("%s is not set. Skipping email notification.", missing)
        # Automatic incident evidence must still exist when email is disabled.
        await session.flush()
        await save_snapshot(session, pending, settings, now)
        return

    rule, state = notification_models(pending)
    context = {
        "rule_name": pending.rule_name,
        "state": pending.state,
        "context_key": pending.context_key,
        "fired_at": as_utc(pending.fired_at),
        "resolved_at": as_utc(pending.resolved_at) if pending.resolved_at else None,
        "alert_level": pending.alert_level,
        "alert_level_label": alert_level_label_ja(pending.alert_level),
        **pending.extra_context,
    }
    try:
        subject, body = NotificationRenderer(settings).render(rule, state, context)
        # Reject malformed header values before committing a permanently undeliverable intent.
        probe = EmailMessage()
        for key, value in (
            ("Subject", subject),
            ("From", settings.alert_email_from),
            ("To", settings.alert_email_to or "(unset)"),
        ):
            probe[key] = value
    except Exception as exc:
        history.success = False
        history.delivery_status = "failed"
        history.error_message = f"notification rendering failed: {exc}"
        history.next_attempt_at = None
        logger.exception(
            "Alert rendering failed rule_id=%s context_key=%s",
            pending.rule_id,
            pending.context_key,
        )
        return

    await session.flush()
    session.add(
        AlertNotificationOutbox(
            history_id=history.id,
            subject=subject,
            body=body,
            from_address=settings.alert_email_from,
            to_address=settings.alert_email_to or "(unset)",
            message_id=make_msgid(domain="vcenter-event-assistant.local"),
            notification={
                "rule_id": pending.rule_id,
                "rule_name": pending.rule_name,
                "rule_type": pending.rule_type,
                "alert_level": pending.alert_level,
                "state": pending.state,
                "context_key": pending.context_key,
                "fired_at": as_utc(pending.fired_at).isoformat(),
                "resolved_at": as_utc(pending.resolved_at).isoformat()
                if pending.resolved_at
                else None,
                "extra_context": pending.extra_context,
                "snapshot_lookback_hours": settings.alert_snapshot_lookback_hours,
            },
            created_at=now,
            expires_at=now + timedelta(seconds=settings.alert_retry_ttl_seconds),
            next_attempt_at=now,
        )
    )


def pending_from_outbox(row: AlertNotificationOutbox) -> PendingAlertNotification:
    payload = row.notification
    return PendingAlertNotification(
        rule_id=payload["rule_id"],
        rule_name=payload["rule_name"],
        rule_type=payload["rule_type"],
        alert_level=payload["alert_level"],
        state=payload["state"],
        context_key=payload["context_key"],
        fired_at=datetime.fromisoformat(payload["fired_at"]),
        resolved_at=datetime.fromisoformat(payload["resolved_at"])
        if payload["resolved_at"]
        else None,
        extra_context=payload["extra_context"],
    )


def retry_delay(settings: Settings, attempt: int) -> int:
    # Saturate without constructing huge integers after many attempts.
    maximum_exponent = settings.alert_retry_max_seconds.bit_length()
    return min(
        settings.alert_retry_initial_seconds * 2 ** min(attempt - 1, maximum_exponent),
        settings.alert_retry_max_seconds,
    )


@dataclass
class DeliverySummary:
    succeeded: int = 0
    retrying: int = 0
    failed: int = 0
    skipped: int = 0


async def _deliver_one(history_id: int, settings: Settings) -> str | None:
    now = utc_now()
    async with session_scope(settings=settings) as session:
        row = await session.get(AlertNotificationOutbox, history_id)
        history = await session.get(AlertHistory, history_id)
        if row is None or history is None:
            return None  # Explicit history/rule deletion cancels queued delivery.
        if as_utc(row.expires_at) <= now:
            history.success = False
            history.delivery_status = "failed"
            history.error_message = f"retry deadline exceeded: {history.error_message or 'delivery not completed'}"
            history.next_attempt_at = None
            await session.delete(row)
            return "failed"
        if as_utc(row.next_attempt_at) > now:
            return None
        history.attempt_count = (history.attempt_count or 0) + 1
        first_attempt = history.attempt_count == 1
        history.last_attempt_at = now
        history.notified_at = now
        row.next_attempt_at = min(
            now + timedelta(seconds=retry_delay(settings, history.attempt_count)),
            as_utc(row.expires_at),
        )
        history.next_attempt_at = row.next_attempt_at
        attempt = history.attempt_count
        is_mock = history.channel == "mock"

    pending = pending_from_outbox(row)
    if first_attempt:
        try:
            async with session_scope(settings=settings) as session:
                snapshot_settings = settings.model_copy(
                    update={
                        "alert_snapshot_lookback_hours": row.notification[
                            "snapshot_lookback_hours"
                        ],
                    }
                )
                await save_snapshot(
                    session, pending, snapshot_settings, as_utc(row.created_at)
                )
        except Exception:
            logger.exception("Snapshot transaction failed history_id=%s", history_id)

    # Recheck cancellation by deletion after snapshot work and before SMTP begins.
    async with session_scope(settings=settings) as session:
        if await session.get(AlertNotificationOutbox, history_id) is None:
            return None
    rule, state = notification_models(pending)
    try:
        if settings.mock_mode and not is_mock:
            outcome = NotificationDeliveryOutcome(
                "none", None, "mock mode enabled; real email skipped"
            )
        else:
            delivery_settings = (
                settings.model_copy(update={"mock_mode": True}) if is_mock else settings
            )
            outcome = await build_notification_channel(delivery_settings).notify(
                rule,
                state,
                row.subject,
                row.body,
                from_address=row.from_address,
                to_address=row.to_address,
                message_id=row.message_id,
            )
    except Exception as exc:
        outcome = NotificationDeliveryOutcome(
            channel="email", success=False, error_message=str(exc)
        )

    finished = utc_now()
    async with session_scope(settings=settings) as session:
        current = await session.get(AlertNotificationOutbox, history_id)
        history = await session.get(AlertHistory, history_id)
        if current is None or history is None:
            return None  # A send already begun cannot be recalled by deletion.
        history.channel = outcome.channel
        history.success = outcome.success
        history.error_message = outcome.error_message
        if outcome.success is True:
            status = "succeeded"
        elif outcome.success is None:
            status = "skipped"
        elif finished >= as_utc(current.expires_at):
            status = "failed"
            history.error_message = f"retry deadline exceeded: {outcome.error_message}"
        else:
            status = "retrying"
            current.next_attempt_at = min(
                finished + timedelta(seconds=retry_delay(settings, attempt)),
                as_utc(current.expires_at),
            )
            history.next_attempt_at = current.next_attempt_at
        history.delivery_status = status
        if status != "retrying":
            history.next_attempt_at = None
            await session.delete(current)
    logger.info(
        "alert delivery history_id=%s rule_id=%s attempt=%s status=%s",
        history_id,
        pending.rule_id,
        attempt,
        status,
    )
    return status


async def deliver_notifications(settings: Settings) -> DeliverySummary:
    """Serial dispatch; a cancelled SMTP thread finishes before releasing the lock."""
    summary = DeliverySummary()
    if _delivery_lock.locked():
        return summary
    async with _delivery_lock:
        now = utc_now()
        async with session_scope(settings=settings) as session:
            ids = list(
                (
                    await session.scalars(
                        select(AlertNotificationOutbox.history_id)
                        .where(
                            or_(
                                AlertNotificationOutbox.next_attempt_at <= now,
                                AlertNotificationOutbox.expires_at <= now,
                            )
                        )
                        .order_by(
                            AlertNotificationOutbox.created_at,
                            AlertNotificationOutbox.history_id,
                        )
                        .limit(settings.alert_delivery_batch_size)
                    )
                ).all()
            )
        for history_id in ids:
            task = asyncio.create_task(_deliver_one(history_id, settings))
            try:
                result = await asyncio.shield(task)
                if result is not None:
                    setattr(summary, result, getattr(summary, result) + 1)
            except asyncio.CancelledError:
                try:
                    await task
                except Exception:
                    logger.exception(
                        "Alert delivery failed during cancellation history_id=%s",
                        history_id,
                    )
                raise
            except Exception:
                logger.exception(
                    "Alert delivery failed history_id=%s; continuing batch", history_id
                )

        async with session_scope(settings=settings) as session:
            count, oldest = (
                await session.execute(
                    select(
                        func.count(AlertNotificationOutbox.history_id),
                        func.min(AlertNotificationOutbox.created_at),
                    )
                )
            ).one()
        age = max(0, (utc_now() - as_utc(oldest)).total_seconds()) if oldest else 0
        logger.info(
            "alert delivery complete queued=%s oldest_age_seconds=%.1f succeeded=%s retrying=%s failed=%s skipped=%s",
            count,
            age,
            summary.succeeded,
            summary.retrying,
            summary.failed,
            summary.skipped,
        )
    return summary
