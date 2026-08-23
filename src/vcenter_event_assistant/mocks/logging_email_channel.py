"""モックモード用: SMTP せずログへ出す通知チャネル。"""

from __future__ import annotations

import logging

from vcenter_event_assistant.db.models import AlertRule, AlertState
from vcenter_event_assistant.services.alerting.notification.base import NotificationChannel
from vcenter_event_assistant.services.alerting.notification.delivery_outcome import (
    NotificationDeliveryOutcome,
)
from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)


class LoggingEmailChannel(NotificationChannel):
    """件名・本文を INFO ログし、送信成功として返す（SMTP なし）。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def notify(
        self,
        rule: AlertRule,
        state: AlertState,
        subject: str,
        body: str,
    ) -> NotificationDeliveryOutcome:
        to_addr = self._settings.alert_email_to or "(unset)"
        logger.info(
            "MOCK_MODE email notification (not sent): to=%s rule=%s subject=%s body_chars=%s",
            to_addr,
            rule.name,
            subject,
            len(body),
        )
        logger.debug("MOCK_MODE email body:\n%s", body)
        return NotificationDeliveryOutcome(channel="mock", success=True)
