"""アラート評価の共通ユーティリティ。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vcenter_event_assistant.db.models import AlertRule, AlertState
    from vcenter_event_assistant.settings import Settings


def as_utc(dt: datetime) -> datetime:
    """naive datetime を UTC aware に正規化する。

    Args:
        dt: タイムゾーン付きまたは naive の日時。

    Returns:
        UTC ``tzinfo`` 付き日時。
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass(frozen=True)
class AlertEvaluationDeps:
    """ルール種別ごとの評価関数が明示的に受け取る依存。"""

    settings: Settings
    notify: Callable[[AlertRule, AlertState, dict], Awaitable[None]]
