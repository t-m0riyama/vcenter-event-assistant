"""通知チャネルの組み立て。"""

from __future__ import annotations

from vcenter_event_assistant.services.alerting.notification.base import NotificationChannel
from vcenter_event_assistant.services.alerting.notification.email_channel import EmailChannel
from vcenter_event_assistant.settings import Settings


def build_notification_channel(settings: Settings) -> NotificationChannel:
    """設定に応じた通知チャネルを返す。``MOCK_MODE`` 時は SMTP しないログチャネル。"""
    if settings.mock_mode:
        from vcenter_event_assistant.mocks.logging_email_channel import LoggingEmailChannel

        return LoggingEmailChannel(settings)
    return EmailChannel(settings)
