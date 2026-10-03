"""アラートルール評価のオーケストレーション。

有効な ``AlertRule`` を種別ごとに評価し、状態・履歴・永続送信予定を保存する。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import AlertRule, AlertState
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alerting.alert_eval_common import (
    AlertEvaluationDeps,
    PendingAlertNotification,
)
from vcenter_event_assistant.services.alerting.alert_eval_event_score import (
    evaluate_event_score_rule,
)
from vcenter_event_assistant.services.alerting.alert_eval_metric import (
    evaluate_metric_threshold_rule,
)
from vcenter_event_assistant.services.alerting.notification_outbox import (
    enqueue_notification,
)
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
    """全有効アラートルールの評価と通知登録を担うファサード。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._last_summary = AlertEvalSummary()

    async def evaluate_all(self) -> AlertEvalSummary:
        """全有効ルールを評価する。"""
        summary = AlertEvalSummary()
        async with session_scope(settings=self._settings) as session:
            res = await session.execute(
                select(AlertRule).where(AlertRule.is_enabled.is_(True))
            )
            rules = res.scalars().all()

        summary.rules_enabled = len(rules)
        for rule in rules:
            deps = AlertEvaluationDeps(
                settings=self._settings, enqueue=self._enqueue_notification
            )
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

        logger.info(
            "alert evaluation complete rules_enabled=%s firings=%s resolutions=%s",
            summary.rules_enabled,
            summary.firings,
            summary.resolutions,
        )
        self._last_summary = summary
        return summary

    async def resolve_event_score_manually(
        self, rule_id: int, context_key: str
    ) -> None:
        """イベントスコア型の発火中アラートを手動で resolved にし、回復通知を登録する。"""
        async with session_scope(settings=self._settings) as session:
            rule = await session.get(AlertRule, rule_id)
            if rule is None:
                raise LookupError("alert rule not found")
            if rule.rule_type != "event_score":
                raise ValueError(
                    "manual resolve is only supported for event_score rules"
                )

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
            await self._enqueue_notification(pending, session)

    async def _enqueue_notification(
        self,
        pending: PendingAlertNotification,
        session: AsyncSession,
    ) -> None:
        """Persist delivery intent in the alert state's transaction; never send SMTP here."""
        await enqueue_notification(session, self._settings, pending)
