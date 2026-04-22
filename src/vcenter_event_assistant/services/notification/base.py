from abc import ABC, abstractmethod
from vcenter_event_assistant.db.models import AlertRule, AlertState

class NotificationChannel(ABC):
    @abstractmethod
    async def notify(self, rule: AlertRule, state: AlertState, subject: str, body: str) -> None:
        """
        通知を送信する。失敗した場合は例外を投げる。
        """
        pass
