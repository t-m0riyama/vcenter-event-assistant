"""通知チャネルの抽象基底。

メール等の具体チャネルは ``NotificationChannel`` を実装する。
"""

from abc import ABC, abstractmethod

from vcenter_event_assistant.db.models import AlertRule, AlertState
from vcenter_event_assistant.services.alerting.notification.delivery_outcome import (
    NotificationDeliveryOutcome,
)


class NotificationChannel(ABC):
    """アラート通知を 1 チャネル分送信するインターフェース。"""

    @abstractmethod
    async def notify(
        self,
        rule: AlertRule,
        state: AlertState,
        subject: str,
        body: str,
    ) -> NotificationDeliveryOutcome:
        """通知を送信する。失敗した場合は例外を投げる。"""
        pass
