"""SMTP 経由のメール通知チャネル。"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from vcenter_event_assistant.db.models import AlertRule, AlertState
from vcenter_event_assistant.services.alerting.notification.base import NotificationChannel
from vcenter_event_assistant.services.alerting.notification.delivery_outcome import (
    NotificationDeliveryOutcome,
)
from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)


def _send_smtp_message(settings: Settings, msg: EmailMessage) -> None:
    """SMTP でメールを送信する（同期。``asyncio.to_thread`` から呼ぶ）。"""
    with smtplib.SMTP(
        settings.smtp_host,
        settings.smtp_port,
        timeout=settings.smtp_timeout_seconds,
    ) as server:
        if settings.smtp_use_tls:
            server.starttls()

        if settings.smtp_username and settings.smtp_password:
            server.login(settings.smtp_username, settings.smtp_password)

        server.send_message(msg)


class EmailChannel(NotificationChannel):
    """設定された SMTP サーバ経由でアラートメールを送信する。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def notify(
        self,
        rule: AlertRule,
        state: AlertState,
        subject: str,
        body: str,
    ) -> NotificationDeliveryOutcome:
        """件名・本文を SMTP で送信する。

        ``SMTP_HOST`` または ``ALERT_EMAIL_TO`` 未設定時はスキップ結果を返す。

        Raises:
            Exception: SMTP 送信に失敗した場合。
        """
        settings = self._settings
        if not settings.smtp_host:
            logger.warning("SMTP_HOST is not set. Skipping email notification.")
            return NotificationDeliveryOutcome(
                channel="none",
                success=None,
                error_message="smtp not configured: SMTP_HOST is not set",
            )

        if not settings.alert_email_to:
            logger.warning("ALERT_EMAIL_TO is not set. Skipping email notification.")
            return NotificationDeliveryOutcome(
                channel="none",
                success=None,
                error_message="smtp not configured: ALERT_EMAIL_TO is not set",
            )

        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        msg["From"] = settings.alert_email_from
        msg["To"] = settings.alert_email_to

        try:
            await asyncio.to_thread(_send_smtp_message, settings, msg)
            logger.info("Email notification sent: %s", subject)
            return NotificationDeliveryOutcome(channel="email", success=True)
        except Exception as e:
            logger.error("Failed to send email notification: %s", e)
            raise
