"""AlertEvaluator の評価サマリログのテスト。"""

from __future__ import annotations

from vcenter_event_assistant.settings import get_settings

import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from vcenter_event_assistant.db.models import AlertRule, MetricSample, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alerting.alert_eval import AlertEvaluator


@pytest.mark.asyncio
async def test_evaluate_all_logs_summary_with_zero_rules(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="vcenter_event_assistant.services.alerting.alert_eval")
    evaluator = AlertEvaluator(get_settings())
    summary = await evaluator.evaluate_all()
    assert summary.rules_enabled == 0
    messages = [r.message for r in caplog.records if r.name == "vcenter_event_assistant.services.alerting.alert_eval"]
    assert any("alert evaluation complete" in m and "rules_enabled=0" in m for m in messages)


@pytest.mark.asyncio
async def test_evaluate_metric_firing_increments_summary_count(caplog: pytest.LogCaptureFixture) -> None:
    async with session_scope() as session:
        vc = VCenter(name="vc_log", host="vc_log", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Log CPU",
            rule_type="metric_threshold",
            is_enabled=True,
            config={"metric_key": "host.cpu.usage_pct", "threshold": 90.0},
        )
        session.add(rule)
        session.add(
            MetricSample(
                vcenter_id=vc.id,
                sampled_at=datetime.now(timezone.utc),
                entity_type="HostSystem",
                entity_moid="host-1",
                entity_name="ESXi-1",
                metric_key="host.cpu.usage_pct",
                value=95.0,
            )
        )
        await session.flush()

    caplog.set_level(logging.INFO, logger="vcenter_event_assistant.services.alerting.alert_eval")
    evaluator = AlertEvaluator(get_settings())
    with patch.object(evaluator.email_channel, "notify", new_callable=AsyncMock):
        summary = await evaluator.evaluate_all()

    assert summary.rules_enabled == 1
    assert summary.firings == 1
    messages = [r.message for r in caplog.records if r.name == "vcenter_event_assistant.services.alerting.alert_eval"]
    assert any("firings=1" in m for m in messages)


@pytest.mark.asyncio
async def test_evaluate_event_score_invalid_config_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with session_scope() as session:
        rule = AlertRule(
            name="Bad Config",
            rule_type="event_score",
            is_enabled=True,
            config={"threshold": "not-a-number"},
        )
        session.add(rule)
        await session.flush()

    caplog.set_level(logging.WARNING, logger="vcenter_event_assistant.services.alerting.alert_eval")
    evaluator = AlertEvaluator(get_settings())
    await evaluator.evaluate_all()
    messages = [r.message for r in caplog.records if r.name == "vcenter_event_assistant.services.alerting.alert_eval"]
    assert any("invalid config" in m for m in messages)
