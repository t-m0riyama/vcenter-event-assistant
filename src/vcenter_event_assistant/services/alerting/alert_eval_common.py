"""アラート評価の共通ユーティリティ。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vcenter_event_assistant.db.models import AlertRule, AlertState
    from vcenter_event_assistant.settings import Settings


def metric_context_key(vcenter_id: uuid.UUID, entity_moid: str) -> str:
    """metric_threshold 用の vCenter スコープ付き context_key。"""
    return f"{vcenter_id}:{entity_moid}"


def is_vcenter_scoped_context_key(context_key: str) -> bool:
    """``{vcenter_id}:{entity_moid}`` 形式かどうか。"""
    if ":" not in context_key:
        return False
    prefix, _rest = context_key.split(":", 1)
    if not prefix or not _rest:
        return False
    try:
        uuid.UUID(prefix)
    except ValueError:
        return False
    return True


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
class PendingAlertNotification:
    """state 確定後に送る通知（セッション外で利用するスナップショット）。"""

    rule_id: int
    rule_name: str
    rule_type: str
    alert_level: str
    state: str
    context_key: str
    fired_at: datetime
    resolved_at: datetime | None
    extra_context: dict[str, Any]


@dataclass
class AlertEvaluationDeps:
    """ルール種別ごとの評価関数が明示的に受け取る依存。"""

    settings: Settings
    _pending: list[PendingAlertNotification] = field(default_factory=list)

    def queue_notify(
        self,
        rule: AlertRule,
        state: AlertState,
        extra_context: dict[str, Any],
    ) -> None:
        """通知をキューに積む（評価セッション commit 後に送る）。"""
        level = getattr(rule, "alert_level", None) or "warning"
        self._pending.append(
            PendingAlertNotification(
                rule_id=rule.id,
                rule_name=rule.name,
                rule_type=rule.rule_type,
                alert_level=str(level),
                state=state.state,
                context_key=state.context_key,
                fired_at=state.fired_at,
                resolved_at=state.resolved_at,
                extra_context=extra_context,
            )
        )

    def drain_pending(self) -> list[PendingAlertNotification]:
        """キューに積んだ通知を取り出してクリアする。"""
        pending = list(self._pending)
        self._pending.clear()
        return pending
