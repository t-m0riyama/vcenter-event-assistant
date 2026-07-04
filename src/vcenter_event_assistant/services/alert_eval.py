"""アラートルール評価のオーケストレーション。

有効な ``AlertRule`` を種別ごとに評価し、通知・履歴・スナップショットを記録する。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from vcenter_event_assistant.alert_levels import alert_level_label_ja
from vcenter_event_assistant.db.models import AlertHistory, AlertRule, AlertState
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alert_eval_event_score import evaluate_event_score_rule
from vcenter_event_assistant.services.alert_eval_metric import evaluate_metric_threshold_rule
from vcenter_event_assistant.services.incident_timeline_snapshot import persist_alert_rule_firing_snapshot
from vcenter_event_assistant.services.notification.email_channel import EmailChannel
from vcenter_event_assistant.services.notification.renderer import NotificationRenderer
from vcenter_event_assistant.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class AlertEvalSummary:
    """1 回の evaluate_all 実行結果の要約。"""

    rules_enabled: int = 0
    firings: int = 0
    resolutions: int = 0


class AlertEvaluator:
    """全有効アラートルールの評価と通知送信を担うファサード。"""

    def __init__(self) -> None:
        self.renderer = NotificationRenderer()
        self.email_channel = EmailChannel()
        self._last_summary = AlertEvalSummary()

    async def evaluate_all(self) -> AlertEvalSummary:
        """全有効ルールを評価する。"""
        summary = AlertEvalSummary()
        async with session_scope() as session:
            res = await session.execute(select(AlertRule).where(AlertRule.is_enabled.is_(True)))
            rules = res.scalars().all()

        summary.rules_enabled = len(rules)
        for rule in rules:
            try:
                if rule.rule_type == "event_score":
                    firings, resolutions = await evaluate_event_score_rule(self, rule)
                elif rule.rule_type == "metric_threshold":
                    firings, resolutions = await evaluate_metric_threshold_rule(self, rule)
                else:
                    firings, resolutions = 0, 0
                summary.firings += firings
                summary.resolutions += resolutions
            except Exception as e:
                logger.error(f"Error evaluating rule {rule.name} ({rule.id}): {e}", exc_info=True)

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
        async with session_scope() as session:
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

            await self._notify(
                rule,
                state,
                {
                    "details": (
                        f"Alert manually resolved for event type: {context_key}"
                    ),
                },
            )

    async def _notify(self, rule: AlertRule, state: AlertState, extra_context: dict) -> None:
        if state.state == "firing":
            settings = get_settings()
            async with session_scope() as session:
                await persist_alert_rule_firing_snapshot(
                    session=session,
                    rule=rule,
                    state=state,
                    details=str(extra_context.get("details", "")),
                    to_time=datetime.now(timezone.utc),
                    lookback_hours=settings.alert_snapshot_lookback_hours,
                )
                await session.commit()

        fired_at = state.fired_at
        if fired_at and fired_at.tzinfo is None:
            fired_at = fired_at.replace(tzinfo=timezone.utc)

        resolved_at = state.resolved_at
        if resolved_at and resolved_at.tzinfo is None:
            resolved_at = resolved_at.replace(tzinfo=timezone.utc)

        level = getattr(rule, "alert_level", None) or "warning"
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

        success = True
        error_msg = None
        try:
            await self.email_channel.notify(rule, state, subject, body)
        except Exception as e:
            success = False
            error_msg = str(e)
            logger.error(f"Failed to send notification for rule {rule.id}: {e}")

        async with session_scope() as session:
            history = AlertHistory(
                rule_id=rule.id,
                alert_level=level,
                state=state.state,
                context_key=state.context_key,
                notified_at=datetime.now(timezone.utc),
                channel="email",
                success=success,
                error_message=error_msg,
            )
            session.add(history)
