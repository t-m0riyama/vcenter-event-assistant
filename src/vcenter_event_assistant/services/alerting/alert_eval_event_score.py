"""イベントスコア型アラートルールの評価。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import select

from vcenter_event_assistant.db.models import AlertRule, AlertState, EventRecord
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alerting.alert_eval_common import as_utc
from vcenter_event_assistant.services.alerting.alert_eval_event_score_config import (
    event_eval_window_start,
    event_score_should_notify,
    merge_latest_qualifying_by_event_type,
    parse_event_score_rule_config,
)
from vcenter_event_assistant.settings import Settings

logger = logging.getLogger("vcenter_event_assistant.services.alerting.alert_eval")


class AlertNotifyProtocol(Protocol):
    """イベントスコア評価から通知送信へ委譲するためのプロトコル。"""

    async def _notify(self, rule: AlertRule, state: AlertState, extra_context: dict) -> None: ...


async def evaluate_event_score_rule(
    notify: AlertNotifyProtocol,
    rule: AlertRule,
    *,
    settings: Settings,
) -> tuple[int, int]:
    """event_score ルールを 1 件評価する。"""
    parsed = parse_event_score_rule_config(rule.config)
    if parsed is None:
        logger.warning("event_score rule=%s id=%s: invalid config", rule.name, rule.id)
        return 0, 0

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
        rows = [(record.event_type, as_utc(record.occurred_at)) for record in records]
        merged = merge_latest_qualifying_by_event_type(rows)

        event_details: dict[str, tuple[str, int]] = {}
        for record in records:
            event_type = record.event_type
            occurred_at = as_utc(record.occurred_at)
            if merged.get(event_type) == occurred_at:
                event_details[event_type] = (record.message, record.notable_score)

        logger.debug(
            "event_score rule=%s lookback_hours=%s window_start=%s qualifying_types=%s",
            rule.name,
            lookback_hours,
            window_start.isoformat(),
            len(merged),
        )

        res = await session.execute(select(AlertState).where(AlertState.rule_id == rule.id))
        states = {state.context_key: state for state in res.scalars().all()}

        for event_type, last_at in merged.items():
            last_at = as_utc(last_at)
            current = states.get(event_type)
            if event_score_should_notify(
                current_state=current.state if current else None,
                last_notified_at=(
                    as_utc(current.last_notified_at)
                    if current and current.last_notified_at
                    else None
                ),
                last_qualifying_at=last_at,
                last_fired_qualifying_at=(
                    as_utc(current.fired_at) if current and current.fired_at else None
                ),
                now=now,
                cooldown_minutes=cooldown,
            ):
                message, score = event_details.get(event_type, ("", 0))
                if not current:
                    notify_state = AlertState(
                        rule_id=rule.id,
                        state="firing",
                        context_key=event_type,
                        fired_at=last_at,
                        last_notified_at=now,
                    )
                    session.add(notify_state)
                else:
                    current.state = "firing"
                    current.fired_at = last_at
                    current.last_notified_at = now
                    current.resolved_at = None
                    notify_state = current
                await session.flush()
                await notify._notify(
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
