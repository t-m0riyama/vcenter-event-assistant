import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
from vcenter_event_assistant.db.models import AlertRule, AlertState, EventRecord, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alert_eval import AlertEvaluator
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
        event_id = event.id

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
        assert state.context_key == str(event_id)


@pytest.mark.asyncio
async def test_evaluate_event_score_resolution():
    async with session_scope() as session:
        vc = VCenter(name="vc2", host="vc2", username="u", password="p")
        session.add(vc)
        await session.flush()

        rule = AlertRule(
            name="Cooldown Test",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 5},
        )
        session.add(rule)
        await session.flush()
        rule_id = rule.id

        state = AlertState(
            rule_id=rule.id,
            state="firing",
            context_key="SomeEvent",
            fired_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        session.add(state)
        await session.flush()

    evaluator = AlertEvaluator()
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.called
        assert mock_notify.call_args[0][1].state == "resolved"

    async with session_scope() as session:
        from sqlalchemy import select

        res = await session.execute(
            select(AlertState).where(AlertState.rule_id == rule_id)
        )
        state = res.scalar_one()
        assert state.state == "resolved"


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
async def test_evaluate_event_score_renotifies_on_second_newer_event() -> None:
    async with session_scope() as session:
        vc = VCenter(name="vc_re2", host="vc_re2", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Renotify2",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 30},
        )
        session.add(rule)
        t1 = datetime.now(timezone.utc) - timedelta(minutes=20)
        ev1 = EventRecord(
            vcenter_id=vc.id,
            occurred_at=t1,
            event_type="E1",
            vmware_key=1,
            notable_score=70,
        )
        session.add(ev1)
        await session.flush()
        rule_id = rule.id
        vcenter_id = vc.id

    evaluator = AlertEvaluator()
    with patch.object(evaluator, "_notify", new_callable=AsyncMock):
        await evaluator.evaluate_all()

    t2 = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with session_scope() as session:
        session.add(
            EventRecord(
                vcenter_id=vcenter_id,
                occurred_at=t2,
                event_type="E2",
                vmware_key=2,
                notable_score=75,
            )
        )
        await session.flush()

    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.call_count == 1

    async with session_scope() as session:
        from sqlalchemy import select

        res = await session.execute(select(AlertState).where(AlertState.rule_id == rule_id))
        st = res.scalar_one()
        assert st.state == "firing"
        assert _as_utc(st.fired_at) == _as_utc(t2)


@pytest.mark.asyncio
async def test_evaluate_event_score_resolves_when_no_qualifying_in_window() -> None:
    async with session_scope() as session:
        vc = VCenter(name="vc_res_win", host="vc_res_win", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Resolve Window",
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
                event_type="Low",
                vmware_key=1,
                notable_score=10,
            )
        )
        session.add(
            AlertState(
                rule_id=rule.id,
                state="firing",
                context_key="99",
                fired_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            )
        )
        await session.flush()

    evaluator = AlertEvaluator()
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.called
        assert mock_notify.call_args[0][1].state == "resolved"


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
