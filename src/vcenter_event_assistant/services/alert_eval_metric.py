"""メトリクス閾値型アラートルールの評価。"""

from __future__ import annotations

import logging
from typing import Protocol

from sqlalchemy import desc, select

from vcenter_event_assistant.db.models import AlertRule, AlertState, MetricSample
from vcenter_event_assistant.db.session import session_scope

logger = logging.getLogger("vcenter_event_assistant.services.alert_eval")


class AlertNotifyProtocol(Protocol):
    async def _notify(self, rule: AlertRule, state: AlertState, extra_context: dict) -> None: ...


async def evaluate_metric_threshold_rule(
    notify: AlertNotifyProtocol,
    rule: AlertRule,
) -> tuple[int, int]:
    """metric_threshold ルールを 1 件評価する。"""
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

        res = await session.execute(select(AlertState).where(AlertState.rule_id == rule.id))
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
                    await notify._notify(
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
                await notify._notify(
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
