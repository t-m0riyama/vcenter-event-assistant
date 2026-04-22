import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from vcenter_event_assistant.db.models import AlertRule, MetricSample, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alert_eval import AlertEvaluator

@pytest.mark.asyncio
async def test_evaluate_metric_threshold_firing_and_resolution():
    async with session_scope() as session:
        vc = VCenter(name="vc_m", host="vc_m", username="u", password="p")
        session.add(vc)
        await session.flush()
        
        rule = AlertRule(
            name="Host CPU High",
            rule_type="metric_threshold",
            config={"metric_key": "cpu.usage", "threshold": 90.0}
        )
        session.add(rule)
        
        # 閾値超えのメトリクス
        s1 = MetricSample(
            vcenter_id=vc.id,
            sampled_at=datetime.now(timezone.utc),
            entity_type="HostSystem",
            entity_moid="host-1",
            entity_name="ESXi-1",
            metric_key="cpu.usage",
            value=95.0
        )
        session.add(s1)
        await session.flush()

    evaluator = AlertEvaluator()
    
    # 1. 発火の確認
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.called
        assert mock_notify.call_args[0][1].state == "firing"
        assert mock_notify.call_args[0][1].context_key == "host-1"

    # 2. 継続（通知が飛ばないこと）
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert not mock_notify.called

    # 3. 回復
    async with session_scope() as session:
        s2 = MetricSample(
            vcenter_id=vc.id,
            sampled_at=datetime.now(timezone.utc),
            entity_type="HostSystem",
            entity_moid="host-1",
            entity_name="ESXi-1",
            metric_key="cpu.usage",
            value=20.0
        )
        session.add(s2)
        await session.flush()

    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.called
        assert mock_notify.call_args[0][1].state == "resolved"
