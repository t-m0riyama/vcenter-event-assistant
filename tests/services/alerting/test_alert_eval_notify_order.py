"""アラート評価の通知順序・履歴記録テスト。"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select

from vcenter_event_assistant.db.models import (
    AlertHistory,
    AlertRule,
    AlertState,
    MetricSample,
    VCenter,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alerting.alert_eval import AlertEvaluator
from vcenter_event_assistant.settings import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_alert_history_records_none_channel_when_smtp_unconfigured(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("ALERT_EMAIL_TO", "")
    get_settings.cache_clear()

    async with session_scope() as session:
        vc = VCenter(name="vc_hist", host="vc_hist", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Hist none",
            rule_type="metric_threshold",
            is_enabled=True,
            config={"metric_key": "cpu.usage", "threshold": 90.0},
        )
        session.add(rule)
        session.add(
            MetricSample(
                vcenter_id=vc.id,
                sampled_at=datetime.now(timezone.utc),
                entity_type="HostSystem",
                entity_moid="host-1",
                entity_name="ESXi-1",
                metric_key="cpu.usage",
                value=95.0,
            )
        )
        await session.flush()
        rule_id = rule.id

    evaluator = AlertEvaluator(get_settings())
    await evaluator.evaluate_all()

    async with session_scope() as session:
        history = (
            (
                await session.execute(
                    select(AlertHistory).where(AlertHistory.rule_id == rule_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(history) == 1
        assert history[0].channel == "none"
        assert history[0].success is None
        assert history[0].error_message is not None


@pytest.mark.asyncio
async def test_evaluate_all_commits_state_before_notification(monkeypatch) -> None:
    """配送ジョブが通知する前に AlertState とキューが commit されている。"""
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("ALERT_EMAIL_TO", "ops@example.com")
    get_settings.cache_clear()
    async with session_scope() as session:
        vc = VCenter(name="vc_order", host="vc_order", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Order",
            rule_type="metric_threshold",
            is_enabled=True,
            config={"metric_key": "cpu.usage", "threshold": 90.0},
        )
        session.add(rule)
        session.add(
            MetricSample(
                vcenter_id=vc.id,
                sampled_at=datetime.now(timezone.utc),
                entity_type="HostSystem",
                entity_moid="host-1",
                entity_name="ESXi-1",
                metric_key="cpu.usage",
                value=95.0,
            )
        )
        await session.flush()
        rule_id = rule.id

    evaluator = AlertEvaluator(get_settings())
    seen: list[str] = []

    async def _capture_notify(*args, **kwargs):
        async with session_scope() as session:
            states = (
                (
                    await session.execute(
                        select(AlertState).where(AlertState.rule_id == rule_id)
                    )
                )
                .scalars()
                .all()
            )
            seen.append(states[0].state if states else "missing")

    from vcenter_event_assistant.services.alerting.notification.email_channel import (
        EmailChannel,
    )
    from vcenter_event_assistant.services.alerting.notification.delivery_outcome import (
        NotificationDeliveryOutcome,
    )
    from vcenter_event_assistant.services.alerting.notification_outbox import (
        deliver_notifications,
    )

    await evaluator.evaluate_all()

    async def capture(*args, **kwargs):
        await _capture_notify()
        return NotificationDeliveryOutcome(channel="email", success=True)

    with patch.object(EmailChannel, "notify", side_effect=capture):
        await deliver_notifications(get_settings())

    assert seen == ["firing"]
