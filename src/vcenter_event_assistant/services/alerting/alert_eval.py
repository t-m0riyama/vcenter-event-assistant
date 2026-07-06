"""アラートルール評価のオーケストレーション。

有効な ``AlertRule`` を種別ごとに評価し、通知・履歴・スナップショットを記録する。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from vcenter_event_assistant.alert_levels import alert_level_label_ja
from vcenter_event_assistant.db.models import AlertHistory, AlertRule, AlertState
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alerting.alert_eval_common import (
    AlertEvaluationDeps,
    PendingAlertNotification,
)
from vcenter_event_assistant.services.alerting.alert_eval_event_score import evaluate_event_score_rule
from vcenter_event_assistant.services.alerting.alert_eval_metric import evaluate_metric_threshold_rule
from vcenter_event_assistant.services.incident_timeline_snapshot import persist_alert_rule_firing_snapshot
from vcenter_event_assistant.services.alerting.notification.delivery_outcome import (
    NotificationDeliveryOutcome,
)
from vcenter_event_assistant.services.alerting.notification.email_channel import EmailChannel
from vcenter_event_assistant.services.alerting.notification.renderer import NotificationRenderer
from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)

RuleEvaluator = Callable[[AlertEvaluationDeps, AlertRule], Awaitable[tuple[int, int]]]

_RULE_EVALUATORS: dict[str, RuleEvaluator] = {
    "event_score": evaluate_event_score_rule,
    "metric_threshold": evaluate_metric_threshold_rule,
}


@dataclass
class AlertEvalSummary:
    """1 回の evaluate_all 実行結果の要約。"""

    rules_enabled: int = 0
    firings: int = 0
    resolutions: int = 0


def _rule_from_pending(pending: PendingAlertNotification) -> AlertRule:
    return AlertRule(
        id=pending.rule_id,
        name=pending.rule_name,
        rule_type=pending.rule_type,
        alert_level=pending.alert_level,
    )


def _state_from_pending(pending: PendingAlertNotification) -> AlertState:
    return AlertState(
        rule_id=pending.rule_id,
        state=pending.state,
        context_key=pending.context_key,
        fired_at=pending.fired_at,
        resolved_at=pending.resolved_at,
    )


def _pending_from_notify_args(
    rule: AlertRule,
    state: AlertState,
    extra_context: dict[str, Any],
) -> PendingAlertNotification:
    level = getattr(rule, "alert_level", None) or "warning"
    return PendingAlertNotification(
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


class AlertEvaluator:
    """全有効アラートルールの評価と通知送信を担うファサード。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.renderer = NotificationRenderer(settings)
        self.email_channel = EmailChannel(settings)
        self._last_summary = AlertEvalSummary()

    async def evaluate_all(self) -> AlertEvalSummary:
        """全有効ルールを評価する。"""
        summary = AlertEvalSummary()
        async with session_scope(settings=self._settings) as session:
            res = await session.execute(select(AlertRule).where(AlertRule.is_enabled.is_(True)))
            rules = res.scalars().all()

        summary.rules_enabled = len(rules)
        for rule in rules:
            deps = AlertEvaluationDeps(settings=self._settings)
            try:
                evaluator_fn = _RULE_EVALUATORS.get(rule.rule_type)
                if evaluator_fn is None:
                    firings, resolutions = 0, 0
                else:
                    firings, resolutions = await evaluator_fn(deps, rule)
                summary.firings += firings
                summary.resolutions += resolutions
            except Exception as e:
                logger.error(
                    "Error evaluating rule %s (%s): %s",
                    rule.name,
                    rule.id,
                    e,
                    exc_info=True,
                )
                continue

            for pending in deps.drain_pending():
                await self._deliver_notification(pending)

        logger.info(
            "alert evaluation complete rules_enabled=%s firings=%s resolutions=%s",
            summary.rules_enabled,
            summary.firings,
            summary.resolutions,
        )
        self._last_summary = summary
        return summary

    async def resolve_event_score_manually(self, rule_id: int, context_key: str) -> None:
        """イベントスコア型の発火中アラートを手動で resolved にし、回復通知を送る。"""
        pending: PendingAlertNotification | None = None
        async with session_scope(settings=self._settings) as session:
            rule = await session.get(AlertRule, rule_id)
            if rule is None:
                raise LookupError("alert rule not found")
            if rule.rule_type != "event_score":
                raise ValueError("manual resolve is only supported for event_score rules")

            res = await session.execute(
                select(AlertState).where(
                    AlertState.rule_id == rule_id,
                    AlertState.context_key == context_key,
                    AlertState.state == "firing",
                )
            )
            state = res.scalar_one_or_none()
            if state is None:
                raise LookupError("no firing alert state for this rule and context")

            now = datetime.now(timezone.utc)
            state.state = "resolved"
            state.resolved_at = now
            await session.flush()

            pending = _pending_from_notify_args(
                rule,
                state,
                {
                    "details": (
                        f"Alert manually resolved for event type: {context_key}"
                    ),
                },
            )

        if pending is not None:
            await self._deliver_notification(pending)

    async def _notify(
        self,
        rule: AlertRule,
        state: AlertState,
        extra_context: dict[str, Any],
    ) -> None:
        """後方互換: 即時通知（テストや将来の直呼び用）。"""
        await self._deliver_notification(
            _pending_from_notify_args(rule, state, extra_context),
        )

    async def _deliver_notification(self, pending: PendingAlertNotification) -> None:
        """state 確定後にスナップショット・メール・履歴を記録する。"""
        rule = _rule_from_pending(pending)
        state = _state_from_pending(pending)
        extra_context = pending.extra_context

        if state.state == "firing":
            async with session_scope(settings=self._settings) as session:
                await persist_alert_rule_firing_snapshot(
                    session=session,
                    rule=rule,
                    state=state,
                    details=str(extra_context.get("details", "")),
                    to_time=datetime.now(timezone.utc),
                    lookback_hours=self._settings.alert_snapshot_lookback_hours,
                )

        fired_at = state.fired_at
        if fired_at and fired_at.tzinfo is None:
            fired_at = fired_at.replace(tzinfo=timezone.utc)

        resolved_at = state.resolved_at
        if resolved_at and resolved_at.tzinfo is None:
            resolved_at = resolved_at.replace(tzinfo=timezone.utc)

        level = pending.alert_level
        context = {
            "rule_name": rule.name,
            "state": state.state,
            "context_key": state.context_key,
            "fired_at": fired_at,
            "resolved_at": resolved_at,
            "alert_level": level,
            "alert_level_label": alert_level_label_ja(level),
            **extra_context,
        }

        subject, body = self.renderer.render(rule, state, context)

        try:
            outcome = await self.email_channel.notify(rule, state, subject, body)
        except Exception as e:
            logger.error("Failed to send notification for rule %s: %s", rule.id, e)
            outcome = NotificationDeliveryOutcome(
                channel="email",
                success=False,
                error_message=str(e),
            )

        async with session_scope(settings=self._settings) as session:
            history = AlertHistory(
                rule_id=rule.id,
                alert_level=level,
                state=state.state,
                context_key=state.context_key,
                notified_at=datetime.now(timezone.utc),
                channel=outcome.channel,
                success=outcome.success,
                error_message=outcome.error_message,
            )
            session.add(history)
