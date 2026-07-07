"""通知送信結果。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationDeliveryOutcome:
    """1 回の通知試行結果（履歴記録用）。"""

    channel: str
    success: bool | None
    error_message: str | None = None
