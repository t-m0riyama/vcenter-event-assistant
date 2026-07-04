from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import desc, select

from vcenter_event_assistant.alert_levels import alert_level_label_ja
from vcenter_event_assistant.db.models import AlertHistory, AlertRule, AlertState, EventRecord, MetricSample
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alert_eval_event_score_config import (
    event_eval_window_start,
    event_score_should_notify,
    merge_latest_qualifying_by_event_type,
    parse_event_score_rule_config,
)
from vcenter_event_assistant.services.incident_timeline_snapshot import persist_alert_rule_firing_snapshot
from vcenter_event_assistant.services.notification.email_channel import EmailChannel
from vcenter_event_assistant.services.notification.renderer import NotificationRenderer
from vcenter_event_assistant.settings import get_settings

logger = logging.getLogger(__name__)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class AlertEvalSummary:
    """1 回の evaluate_all 実行結果の要約。"""

    rules_enabled: int = 0
    firings: int = 0
    resolutions: int = 0


class AlertEvaluator:
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
                    firings, resolutions = await self._evaluate_event_score(rule)
                elif rule.rule_type == "metric_threshold":
                    firings, resolutions = await self._evaluate_metric_threshold(rule)
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

    async def _evaluate_event_score(self, rule: AlertRule) -> tuple[int, int]:
        parsed = parse_event_score_rule_config(rule.config)
        if parsed is None:
            logger.warning("event_score rule=%s id=%s: invalid config", rule.name, rule.id)
            return 0, 0

        settings = get_settings()
        lookback_hours = settings.alert_event_eval_lookback_hours
        now = datetime.now(timezone.utc)
        window_start = event_eval_window_start(now=now, lookback_hours=lookback_hours)
        threshold = parsed.threshold
        cooldown = parsed.cooldown_minutes
        firings = 0
        resolutions = 0

        async with session_scope() as session:
            res = await session.execute(
                select(
                    EventRecord.event_type,
                    EventRecord.occurred_at,
                    EventRecord.message,
                    EventRecord.notable_score,
                ).where(
                    EventRecord.notable_score >= threshold,
                    EventRecord.occurred_at >= window_start,
                )
            )
            records = res.all()
            rows = [(record.event_type, _as_utc(record.occurred_at)) for record in records]
            merged = merge_latest_qualifying_by_event_type(rows)

            event_details: dict[str, tuple[str, int]] = {}
            for record in records:
                event_type = record.event_type
                occurred_at = _as_utc(record.occurred_at)
                if merged.get(event_type) == occurred_at:
                    event_details[event_type] = (record.message, record.notable_score)

            logger.debug(
                "event_score rule=%s lookback_hours=%s window_start=%s qualifying_types=%s",
                rule.name,
                lookback_hours,
                window_start.isoformat(),
                len(merged),
            )

            res = await session.execute(
                select(AlertState).where(AlertState.rule_id == rule.id)
            )
            states = {state.context_key: state for state in res.scalars().all()}

            for event_type, last_at in merged.items():
                last_at = _as_utc(last_at)
                current = states.get(event_type)
                if event_score_should_notify(
                    current_state=current.state if current else None,
                    last_notified_at=(
                        _as_utc(current.last_notified_at)
                        if current and current.last_notified_at
                        else None
                    ),
                    last_qualifying_at=last_at,
                    now=now,
                    cooldown_minutes=cooldown,
                ):
                    message, score = event_details.get(event_type, ("", 0))
                    if not current or current.state == "resolved":
                        notify_state = AlertState(
                            rule_id=rule.id,
                            state="firing",
                            context_key=event_type,
                            fired_at=last_at,
                            last_notified_at=now,
                        )
                        session.add(notify_state)
                        if current:
                            await session.delete(current)
                    else:
                        current.fired_at = last_at
                        current.last_notified_at = now
                        notify_state = current
                    await session.flush()
                    await self._notify(
                        rule,
                        notify_state,
                        {
                            "details": (
                                f"Notable event detected: {message} "
                                f"(Score: {score})"
                            ),
                        },
                    )
                    firings += 1
                elif current and current.state == "firing":
                    current.fired_at = last_at

        return firings, resolutions

    async def _evaluate_metric_threshold(self, rule: AlertRule) -> tuple[int, int]:
        metric_key = rule.config.get("metric_key")
        threshold = rule.config.get("threshold")
        if not metric_key or threshold is None:
            return 0, 0

        firings = 0
        resolutions = 0

        async with session_scope() as session:
            res = await session.execute(
                select(MetricSample)
                .where(MetricSample.metric_key == metric_key)
                .order_by(MetricSample.entity_moid, desc(MetricSample.sampled_at))
            )
            latest_samples: dict[str, MetricSample] = {}
            for sample in res.scalars().all():
                if sample.entity_moid not in latest_samples:
                    latest_samples[sample.entity_moid] = sample

            if not latest_samples:
                logger.debug(
                    "metric_threshold rule=%s metric_key=%s: no samples in DB",
                    rule.name,
                    metric_key,
                )
                return 0, 0

            res = await session.execute(
                select(AlertState).where(AlertState.rule_id == rule.id)
            )
            states = {st.context_key: st for st in res.scalars().all()}

            for moid, sample in latest_samples.items():
                is_above = sample.value >= threshold
                current = states.get(moid)

                if is_above:
                    if not current or current.state == "resolved":
                        new_state = AlertState(
                            rule_id=rule.id,
                            state="firing",
                            context_key=moid,
                            fired_at=sample.sampled_at,
                        )
                        session.add(new_state)
                        if current:
                            await session.delete(current)
                        await session.flush()
                        await self._notify(
                            rule,
                            new_state,
                            {
                                "details": (
                                    f"Metric {metric_key} reached {sample.value} "
                                    f"(threshold: {threshold}) on {sample.entity_name}"
                                ),
                            },
                        )
                        firings += 1
                elif current and current.state == "firing":
                    current.state = "resolved"
                    current.resolved_at = sample.sampled_at
                    await session.flush()
                    await self._notify(
                        rule,
                        current,
                        {
                            "details": (
                                f"Metric {metric_key} dropped to {sample.value} "
                                f"(threshold: {threshold}) on {sample.entity_name}"
                            ),
                        },
                    )
                    resolutions += 1

        return firings, resolutions

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
