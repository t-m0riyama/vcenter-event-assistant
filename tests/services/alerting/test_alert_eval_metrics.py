import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from vcenter_event_assistant.db.models import AlertRule, AlertState, MetricSample, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alerting.alert_eval import AlertEvaluator
from vcenter_event_assistant.settings import get_settings

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

    evaluator = AlertEvaluator(get_settings())
    
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


@pytest.mark.asyncio
async def test_metric_threshold_does_not_fire_when_metric_key_mismatches_collector() -> None:
    async with session_scope() as session:
        vc = VCenter(name="vc_key", host="vc_key", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Wrong key",
            rule_type="metric_threshold",
            is_enabled=True,
            config={"metric_key": "cpu.usage.average", "threshold": 90.0},
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

    evaluator = AlertEvaluator(get_settings())
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert not mock_notify.called


@pytest.mark.asyncio
async def test_metric_threshold_fires_when_metric_key_matches_collector() -> None:
    async with session_scope() as session:
        vc = VCenter(name="vc_ok", host="vc_ok", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Right key",
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

    evaluator = AlertEvaluator(get_settings())
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.called


@pytest.mark.asyncio
async def test_metric_threshold_uses_latest_sample_per_entity() -> None:
    async with session_scope() as session:
        vc = VCenter(name="vc_hist", host="vc_hist", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Latest sample",
            rule_type="metric_threshold",
            config={"metric_key": "cpu.usage", "threshold": 90.0},
        )
        session.add(rule)
        now = datetime.now(timezone.utc)
        session.add(
            MetricSample(
                vcenter_id=vc.id,
                sampled_at=now - timedelta(hours=2),
                entity_type="HostSystem",
                entity_moid="host-1",
                entity_name="ESXi-1",
                metric_key="cpu.usage",
                value=99.0,
            )
        )
        session.add(
            MetricSample(
                vcenter_id=vc.id,
                sampled_at=now,
                entity_type="HostSystem",
                entity_moid="host-1",
                entity_name="ESXi-1",
                metric_key="cpu.usage",
                value=20.0,
            )
        )
        await session.flush()

    evaluator = AlertEvaluator(get_settings())
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_metric_threshold_refires_by_updating_resolved_state() -> None:
    async with session_scope() as session:
        vc = VCenter(name="vc_upsert_m", host="vc_upsert_m", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Upsert metric",
            rule_type="metric_threshold",
            config={"metric_key": "cpu.usage", "threshold": 90.0},
        )
        session.add(rule)
        await session.flush()
        now = datetime.now(timezone.utc)
        existing = AlertState(
            rule_id=rule.id,
            state="resolved",
            context_key="host-1",
            fired_at=now - timedelta(hours=2),
            resolved_at=now - timedelta(hours=1),
        )
        session.add(existing)
        session.add(
            MetricSample(
                vcenter_id=vc.id,
                sampled_at=now,
                entity_type="HostSystem",
                entity_moid="host-1",
                entity_name="ESXi-1",
                metric_key="cpu.usage",
                value=95.0,
            )
        )
        await session.flush()
        state_id = existing.id
        rule_id = rule.id

    evaluator = AlertEvaluator(get_settings())
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.call_count == 1

    async with session_scope() as session:
        from sqlalchemy import select

        states = (
            await session.execute(select(AlertState).where(AlertState.rule_id == rule_id))
        ).scalars().all()
        assert len(states) == 1
        assert states[0].id == state_id
        assert states[0].state == "firing"
        assert states[0].resolved_at is None
