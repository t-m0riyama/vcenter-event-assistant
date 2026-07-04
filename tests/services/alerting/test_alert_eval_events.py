import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
from vcenter_event_assistant.db.models import AlertRule, AlertState, EventRecord, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alerting.alert_eval import AlertEvaluator
from vcenter_event_assistant.settings import get_settings


@pytest.mark.asyncio
async def test_evaluate_event_score_firing():
    async with session_scope() as session:
        vc = VCenter(name="vc1", host="vc1", username="u", password="p")
        session.add(vc)
        await session.flush()

        rule = AlertRule(
            name="High Score Event",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 5},
        )
        session.add(rule)

        event = EventRecord(
            vcenter_id=vc.id,
            occurred_at=datetime.now(timezone.utc),
            event_type="HostConnectionLostEvent",
            vmware_key=1,
            notable_score=70,
        )
        session.add(event)
        await session.flush()
        rule_id = rule.id

    evaluator = AlertEvaluator()
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.called

    async with session_scope() as session:
        from sqlalchemy import select

        res = await session.execute(
            select(AlertState).where(AlertState.rule_id == rule_id)
        )
        state = res.scalar_one()
        assert state.state == "firing"
        assert state.context_key == "HostConnectionLostEvent"


@pytest.mark.asyncio
async def test_evaluate_event_score_does_not_auto_resolve_when_no_qualifying_in_window() -> None:
    """イベントスコア型は沈黙でも自動回復しない（spec R4）。"""
    async with session_scope() as session:
        vc = VCenter(name="vc_no_auto_res", host="h", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="No Auto Resolve",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 5},
        )
        session.add(rule)
        await session.flush()
        rule_id = rule.id
        session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                event_type="LowOnly",
                vmware_key=1,
                notable_score=10,
            )
        )
        session.add(
            AlertState(
                rule_id=rule.id,
                state="firing",
                context_key="vim.event.WasFiring",
                fired_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            )
        )
        await session.flush()

    evaluator = AlertEvaluator()
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        mock_notify.assert_not_called()

    async with session_scope() as session:
        from sqlalchemy import select

        res = await session.execute(select(AlertState).where(AlertState.rule_id == rule_id))
        st = res.scalar_one()
        assert st.state == "firing"
        assert st.context_key == "vim.event.WasFiring"


@pytest.mark.asyncio
async def test_evaluate_event_score_ignores_high_score_outside_lookback_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALERT_EVENT_EVAL_LOOKBACK_HOURS", "2")
    get_settings.cache_clear()
    try:
        async with session_scope() as session:
            vc = VCenter(name="vc_window", host="vc_window", username="u", password="p")
            session.add(vc)
            await session.flush()
            rule = AlertRule(
                name="Window Test",
                rule_type="event_score",
                config={"threshold": 60, "cooldown_minutes": 5},
            )
            session.add(rule)
            session.add(
                EventRecord(
                    vcenter_id=vc.id,
                    occurred_at=datetime.now(timezone.utc) - timedelta(hours=5),
                    event_type="OldEvent",
                    vmware_key=1,
                    notable_score=90,
                )
            )
            await session.flush()
            rule_id = rule.id

        evaluator = AlertEvaluator()
        with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
            await evaluator.evaluate_all()
            mock_notify.assert_not_called()

        async with session_scope() as session:
            from sqlalchemy import select

            res = await session.execute(select(AlertState).where(AlertState.rule_id == rule_id))
            assert res.scalar_one_or_none() is None
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_evaluate_event_score_firing_with_string_threshold_in_config() -> None:
    async with session_scope() as session:
        vc = VCenter(name="vc_str", host="vc_str", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="String Threshold",
            rule_type="event_score",
            config={"threshold": "60", "cooldown_minutes": 5},
        )
        session.add(rule)
        session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=datetime.now(timezone.utc),
                event_type="Evt",
                vmware_key=2,
                notable_score=70,
            )
        )
        await session.flush()
        rule_id = rule.id

    evaluator = AlertEvaluator()
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.called

    async with session_scope() as session:
        from sqlalchemy import select

        res = await session.execute(select(AlertState).where(AlertState.rule_id == rule_id))
        assert res.scalar_one().state == "firing"


@pytest.mark.asyncio
async def test_evaluate_event_score_suppresses_renotify_within_cooldown_same_type() -> None:
    async with session_scope() as session:
        vc = VCenter(name="vc_cd", host="h", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Cooldown Interval",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 10},
        )
        session.add(rule)
        t1 = datetime.now(timezone.utc) - timedelta(minutes=5)
        session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=t1,
                event_type="vim.event.UserLoginSessionEvent",
                vmware_key=1,
                notable_score=70,
            )
        )
        await session.flush()
        vcenter_id = vc.id

    evaluator = AlertEvaluator()
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.call_count == 1

    t2 = datetime.now(timezone.utc) - timedelta(minutes=2)
    async with session_scope() as session:
        session.add(
            EventRecord(
                vcenter_id=vcenter_id,
                occurred_at=t2,
                event_type="vim.event.UserLoginSessionEvent",
                vmware_key=2,
                notable_score=75,
            )
        )
        await session.flush()

    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_evaluate_event_score_independent_state_per_event_type() -> None:
    async with session_scope() as session:
        vc = VCenter(name="vc_ind", host="h", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Per Type",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 30},
        )
        session.add(rule)
        now = datetime.now(timezone.utc)
        session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=now - timedelta(minutes=5),
                event_type="vim.event.UserLoginSessionEvent",
                vmware_key=1,
                notable_score=70,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=now - timedelta(minutes=3),
                event_type="vim.event.UserLogoutSessionEvent",
                vmware_key=2,
                notable_score=80,
            )
        )
        await session.flush()
        rule_id = rule.id

    evaluator = AlertEvaluator()
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.call_count == 2

    async with session_scope() as session:
        from sqlalchemy import select

        res = await session.execute(select(AlertState).where(AlertState.rule_id == rule_id))
        states = {s.context_key: s for s in res.scalars().all()}
        assert set(states) == {
            "vim.event.UserLoginSessionEvent",
            "vim.event.UserLogoutSessionEvent",
        }
        assert all(s.state == "firing" for s in states.values())


@pytest.mark.asyncio
async def test_evaluate_event_score_renotifies_after_cooldown_same_type() -> None:
    async with session_scope() as session:
        vc = VCenter(name="vc_re_cd", host="h", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Renotify After Cooldown",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 10},
        )
        session.add(rule)
        t1 = datetime.now(timezone.utc) - timedelta(minutes=20)
        session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=t1,
                event_type="vim.event.E1",
                vmware_key=1,
                notable_score=70,
            )
        )
        await session.flush()
        rule_id = rule.id
        vcenter_id = vc.id

    evaluator = AlertEvaluator()
    with patch.object(evaluator, "_notify", new_callable=AsyncMock):
        await evaluator.evaluate_all()

    async with session_scope() as session:
        from sqlalchemy import select

        st = (
            await session.execute(select(AlertState).where(AlertState.rule_id == rule_id))
        ).scalar_one()
        st.last_notified_at = datetime.now(timezone.utc) - timedelta(minutes=11)
        await session.flush()

    t2 = datetime.now(timezone.utc) - timedelta(minutes=1)
    async with session_scope() as session:
        session.add(
            EventRecord(
                vcenter_id=vcenter_id,
                occurred_at=t2,
                event_type="vim.event.E1",
                vmware_key=2,
                notable_score=75,
            )
        )
        await session.flush()

    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.call_count == 1


@pytest.mark.asyncio
async def test_evaluate_event_score_does_not_renotify_after_cooldown_without_new_qualifying() -> None:
    async with session_scope() as session:
        vc = VCenter(name="vc_stale", host="h", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Stale Qualifying",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 10},
        )
        session.add(rule)
        t1 = datetime.now(timezone.utc) - timedelta(minutes=20)
        session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=t1,
                event_type="vim.event.E1",
                vmware_key=1,
                notable_score=70,
            )
        )
        await session.flush()
        rule_id = rule.id

    evaluator = AlertEvaluator()
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.call_count == 1

    async with session_scope() as session:
        from sqlalchemy import select

        st = (
            await session.execute(select(AlertState).where(AlertState.rule_id == rule_id))
        ).scalar_one()
        st.last_notified_at = datetime.now(timezone.utc) - timedelta(minutes=11)
        await session.flush()

    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_evaluate_event_score_refires_by_updating_resolved_state() -> None:
    async with session_scope() as session:
        vc = VCenter(name="vc_upsert", host="h", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Upsert Refire",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 5},
        )
        session.add(rule)
        await session.flush()
        now = datetime.now(timezone.utc)
        existing = AlertState(
            rule_id=rule.id,
            state="resolved",
            context_key="vim.event.E1",
            fired_at=now - timedelta(hours=2),
            resolved_at=now - timedelta(hours=1),
        )
        session.add(existing)
        session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=now - timedelta(minutes=1),
                event_type="vim.event.E1",
                vmware_key=1,
                notable_score=70,
            )
        )
        await session.flush()
        state_id = existing.id
        rule_id = rule.id

    evaluator = AlertEvaluator()
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


@pytest.mark.asyncio
async def test_evaluate_event_score_firing_notify_uses_event_type_in_context_key() -> None:
    """メール件名の Resource（context_key）にイベント種別が出ること。"""
    async with session_scope() as session:
        vc = VCenter(name="vc_type", host="vc_type", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Type In Subject",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 5},
        )
        session.add(rule)
        session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=datetime.now(timezone.utc),
                event_type="vim.event.UserLoginSessionEvent",
                vmware_key=99,
                notable_score=65,
            )
        )
        await session.flush()

    evaluator = AlertEvaluator()
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        notify_state = mock_notify.call_args[0][1]
        assert notify_state.context_key == "vim.event.UserLoginSessionEvent"
        assert not notify_state.context_key.isdigit()
