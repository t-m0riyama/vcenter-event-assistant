import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, select

from vcenter_event_assistant.db.models import AlertRule, AlertState, MetricSample, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alerting.alert_eval import AlertEvaluator
from vcenter_event_assistant.services.alerting.alert_eval_common import metric_context_key
from vcenter_event_assistant.settings import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_evaluate_metric_threshold_firing_and_resolution():
    async with session_scope() as session:
        vc = VCenter(name="vc_m", host="vc_m", username="u", password="p")
        session.add(vc)
        await session.flush()
        vc_id = vc.id

        rule = AlertRule(
            name="Host CPU High",
            rule_type="metric_threshold",
            config={"metric_key": "cpu.usage", "threshold": 90.0},
        )
        session.add(rule)

        s1 = MetricSample(
            vcenter_id=vc.id,
            sampled_at=datetime.now(timezone.utc),
            entity_type="HostSystem",
            entity_moid="host-1",
            entity_name="ESXi-1",
            metric_key="cpu.usage",
            value=95.0,
        )
        session.add(s1)
        await session.flush()

    evaluator = AlertEvaluator(get_settings())

    # 1. 発火の確認
    with patch.object(evaluator, "_enqueue_notification", new_callable=AsyncMock) as mock_deliver:
        await evaluator.evaluate_all()
        assert mock_deliver.called
        pending = mock_deliver.call_args[0][0]
        assert pending.state == "firing"
        assert pending.context_key == metric_context_key(vc_id, "host-1")

    # 2. 継続（通知が飛ばないこと）
    with patch.object(evaluator, "_enqueue_notification", new_callable=AsyncMock) as mock_deliver:
        await evaluator.evaluate_all()
        assert not mock_deliver.called

    async with session_scope() as session:
        s2 = MetricSample(
            vcenter_id=vc_id,
            sampled_at=datetime.now(timezone.utc),
            entity_type="HostSystem",
            entity_moid="host-1",
            entity_name="ESXi-1",
            metric_key="cpu.usage",
            value=20.0,
        )
        session.add(s2)
        await session.flush()

    with patch.object(evaluator, "_enqueue_notification", new_callable=AsyncMock) as mock_deliver:
        await evaluator.evaluate_all()
        assert mock_deliver.called
        pending = mock_deliver.call_args[0][0]
        assert pending.state == "resolved"


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
    with patch.object(evaluator, "_enqueue_notification", new_callable=AsyncMock) as mock_deliver:
        await evaluator.evaluate_all()
        assert not mock_deliver.called


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
    with patch.object(evaluator, "_enqueue_notification", new_callable=AsyncMock) as mock_deliver:
        await evaluator.evaluate_all()
        assert mock_deliver.called


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
    with patch.object(evaluator, "_enqueue_notification", new_callable=AsyncMock) as mock_deliver:
        await evaluator.evaluate_all()
        mock_deliver.assert_not_called()


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
        context_key = metric_context_key(vc.id, "host-1")
        existing = AlertState(
            rule_id=rule.id,
            state="resolved",
            context_key=context_key,
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
    with patch.object(evaluator, "_enqueue_notification", new_callable=AsyncMock) as mock_deliver:
        await evaluator.evaluate_all()
        assert mock_deliver.call_count == 1

    async with session_scope() as session:
        states = (
            await session.execute(select(AlertState).where(AlertState.rule_id == rule_id))
        ).scalars().all()
        assert len(states) == 1
        assert states[0].id == state_id
        assert states[0].state == "firing"
        assert states[0].resolved_at is None


@pytest.mark.asyncio
async def test_metric_threshold_separates_same_moid_across_vcenters() -> None:
    async with session_scope() as session:
        vc1 = VCenter(name="vc_a", host="vc_a", username="u", password="p")
        vc2 = VCenter(name="vc_b", host="vc_b", username="u", password="p")
        session.add_all([vc1, vc2])
        await session.flush()
        rule = AlertRule(
            name="CPU both",
            rule_type="metric_threshold",
            is_enabled=True,
            config={"metric_key": "cpu.usage", "threshold": 90.0},
        )
        session.add(rule)
        now = datetime.now(timezone.utc)
        for vc in (vc1, vc2):
            session.add(
                MetricSample(
                    vcenter_id=vc.id,
                    sampled_at=now,
                    entity_type="HostSystem",
                    entity_moid="host-10",
                    entity_name=f"ESXi-{vc.name}",
                    metric_key="cpu.usage",
                    value=95.0,
                )
            )
        await session.flush()

    evaluator = AlertEvaluator(get_settings())
    with patch.object(evaluator, "_enqueue_notification", new_callable=AsyncMock) as mock_deliver:
        await evaluator.evaluate_all()
        assert mock_deliver.call_count == 2
        keys = {call.args[0].context_key for call in mock_deliver.call_args_list}
        assert len(keys) == 2


@pytest.mark.asyncio
async def test_metric_threshold_firing_becomes_stale_and_notifies_once(monkeypatch) -> None:
    monkeypatch.setenv("METRIC_STALENESS_WINDOW_SECONDS", "300")
    get_settings.cache_clear()

    async with session_scope() as session:
        vc = VCenter(name="vc_stale", host="vc_stale", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Stale metric",
            rule_type="metric_threshold",
            is_enabled=True,
            config={"metric_key": "cpu.usage", "threshold": 90.0},
        )
        session.add(rule)
        now = datetime.now(timezone.utc)
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
        rule_id = rule.id
        vc_id = vc.id

    evaluator = AlertEvaluator(get_settings())
    with patch.object(evaluator, "_enqueue_notification", new_callable=AsyncMock) as mock_deliver:
        await evaluator.evaluate_all()
        assert mock_deliver.call_count == 1

    async with session_scope() as session:
        await session.execute(delete(MetricSample))
        session.add(
            MetricSample(
                vcenter_id=vc_id,
                sampled_at=now - timedelta(hours=2),
                entity_type="HostSystem",
                entity_moid="host-1",
                entity_name="ESXi-1",
                metric_key="cpu.usage",
                value=95.0,
            )
        )

    with patch.object(evaluator, "_enqueue_notification", new_callable=AsyncMock) as mock_deliver:
        await evaluator.evaluate_all()
        assert mock_deliver.call_count == 1
        assert mock_deliver.call_args[0][0].state == "stale"

    async with session_scope() as session:
        state = (
            await session.execute(select(AlertState).where(AlertState.rule_id == rule_id))
        ).scalar_one()
        assert state.state == "stale"

    with patch.object(evaluator, "_enqueue_notification", new_callable=AsyncMock) as mock_deliver:
        await evaluator.evaluate_all()
        mock_deliver.assert_not_called()


@pytest.mark.asyncio
async def test_metric_threshold_fires_for_hosts_of_every_vcenter() -> None:
    """vCenter を指定しない評価で、登録済みのすべての vCenter の最新サンプルを見る（Issue #310）。"""
    now = datetime.now(timezone.utc)
    async with session_scope() as session:
        vc1 = VCenter(name="vc_all_1", host="vc_all_1", username="u", password="p")
        vc2 = VCenter(name="vc_all_2", host="vc_all_2", username="u", password="p")
        session.add_all([vc1, vc2])
        await session.flush()
        session.add(
            AlertRule(
                name="CPU every vCenter",
                rule_type="metric_threshold",
                is_enabled=True,
                config={"metric_key": "cpu.usage", "threshold": 90.0},
            )
        )
        for vc, moid, latest in ((vc1, "host-1", 95.0), (vc2, "host-2", 96.0)):
            for at, value in ((now - timedelta(minutes=1), 10.0), (now, latest)):
                session.add(
                    MetricSample(
                        vcenter_id=vc.id,
                        sampled_at=at,
                        entity_type="HostSystem",
                        entity_moid=moid,
                        entity_name=f"ESXi-{moid}",
                        metric_key="cpu.usage",
                        value=value,
                    )
                )
        await session.flush()
        expected = {metric_context_key(vc1.id, "host-1"), metric_context_key(vc2.id, "host-2")}

    evaluator = AlertEvaluator(get_settings())
    with patch.object(evaluator, "_enqueue_notification", new_callable=AsyncMock) as mock_deliver:
        await evaluator.evaluate_all()
    assert {call.args[0].context_key for call in mock_deliver.call_args_list} == expected
    assert {call.args[0].state for call in mock_deliver.call_args_list} == {"firing"}


@pytest.mark.asyncio
async def test_metric_threshold_evaluates_samples_of_disabled_vcenter() -> None:
    """無効にした vCenter の新しいサンプルも評価し、状態を作る（評価は vCenter の有効・無効を見ない）。"""
    now = datetime.now(timezone.utc)
    async with session_scope() as session:
        enabled = VCenter(name="vc_on", host="vc_on", username="u", password="p")
        disabled = VCenter(name="vc_off", host="vc_off", username="u", password="p", is_enabled=False)
        session.add_all([enabled, disabled])
        await session.flush()
        rule = AlertRule(
            name="CPU disabled vCenter",
            rule_type="metric_threshold",
            is_enabled=True,
            config={"metric_key": "cpu.usage", "threshold": 90.0},
        )
        session.add(rule)
        for vc in (enabled, disabled):
            session.add(
                MetricSample(
                    vcenter_id=vc.id,
                    sampled_at=now,
                    entity_type="HostSystem",
                    entity_moid="host-1",
                    entity_name=f"ESXi-{vc.name}",
                    metric_key="cpu.usage",
                    value=95.0,
                )
            )
        await session.flush()
        rule_id = rule.id
        expected = {metric_context_key(enabled.id, "host-1"), metric_context_key(disabled.id, "host-1")}

    evaluator = AlertEvaluator(get_settings())
    with patch.object(evaluator, "_enqueue_notification", new_callable=AsyncMock):
        await evaluator.evaluate_all()

    async with session_scope() as session:
        states = (await session.execute(select(AlertState).where(AlertState.rule_id == rule_id))).scalars().all()
    assert {st.context_key for st in states} == expected
    assert {st.state for st in states} == {"firing"}


@pytest.mark.asyncio
async def test_metric_threshold_without_any_vcenter_does_not_notify() -> None:
    """vCenter が 1 つも無い（サンプルも無い）ときは、何も通知しない（Issue #310）。"""
    async with session_scope() as session:
        session.add(
            AlertRule(
                name="CPU no vCenter",
                rule_type="metric_threshold",
                is_enabled=True,
                config={"metric_key": "cpu.usage", "threshold": 90.0},
            )
        )

    evaluator = AlertEvaluator(get_settings())
    with patch.object(evaluator, "_enqueue_notification", new_callable=AsyncMock) as mock_deliver:
        await evaluator.evaluate_all()
        mock_deliver.assert_not_called()


@pytest.mark.asyncio
async def test_metric_threshold_firing_becomes_stale_after_last_vcenter_is_deleted() -> None:
    """最後の vCenter を消してサンプルが CASCADE で消えても、発火中の状態は stale にして 1 回だけ通知する。"""
    async with session_scope() as session:
        vc = VCenter(name="vc_gone", host="vc_gone", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="CPU vCenter deleted",
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
        vc_id = vc.id

    evaluator = AlertEvaluator(get_settings())
    with patch.object(evaluator, "_enqueue_notification", new_callable=AsyncMock) as mock_deliver:
        await evaluator.evaluate_all()
        assert mock_deliver.call_count == 1

    async with session_scope() as session:
        await session.execute(delete(VCenter).where(VCenter.id == vc_id))
    async with session_scope() as session:
        assert (await session.execute(select(MetricSample))).scalars().all() == []

    with patch.object(evaluator, "_enqueue_notification", new_callable=AsyncMock) as mock_deliver:
        await evaluator.evaluate_all()
        assert mock_deliver.call_count == 1
        assert mock_deliver.call_args[0][0].state == "stale"

    async with session_scope() as session:
        state = (await session.execute(select(AlertState).where(AlertState.rule_id == rule_id))).scalar_one()
        assert state.state == "stale"
