import pytest
from sqlalchemy import select
from vcenter_event_assistant.db.models import AlertRule, AlertState, AlertHistory
from vcenter_event_assistant.db.session import session_scope
from datetime import datetime, timezone

@pytest.mark.asyncio
async def test_create_alert_rule():
    async with session_scope() as db_session:
        rule = AlertRule(
            name="High CPU",
            rule_type="metric_threshold",
            config={"metric_key": "host.cpu.usage_pct", "threshold": 90.0}
        )
        db_session.add(rule)
        await db_session.flush()
        
        res = await db_session.execute(select(AlertRule).where(AlertRule.name == "High CPU"))
        saved = res.scalar_one()
        assert saved.id is not None
        assert saved.rule_type == "metric_threshold"
        assert saved.config["threshold"] == 90.0
        assert isinstance(saved.created_at, datetime)

@pytest.mark.asyncio
async def test_alert_state_relationship():
    async with session_scope() as db_session:
        rule = AlertRule(name="Event Alert", rule_type="event_score")
        db_session.add(rule)
        await db_session.flush()
        
        state = AlertState(
            rule_id=rule.id,
            state="firing",
            context_key="HostConnectionLostEvent",
            fired_at=datetime.now(timezone.utc)
        )
        db_session.add(state)
        await db_session.flush()
        
        # 相互関係の確認（リレーションシップを明示的にリフレッシュ）
        await db_session.refresh(rule, ["states"])
        assert len(rule.states) == 1
        assert rule.states[0].context_key == "HostConnectionLostEvent"
        
        # state 側からの rule アクセスも確認
        await db_session.refresh(state, ["rule"])
        assert state.rule.name == "Event Alert"

@pytest.mark.asyncio
async def test_alert_history_relationship():
    async with session_scope() as db_session:
        rule = AlertRule(name="History Test", rule_type="event_score")
        db_session.add(rule)
        await db_session.flush()
        
        hist = AlertHistory(
            rule_id=rule.id,
            state="firing",
            context_key="test-key",
            notified_at=datetime.now(timezone.utc),
            channel="email",
            success=True
        )
        db_session.add(hist)
        await db_session.flush()
        
        await db_session.refresh(rule, ["history"])
        assert len(rule.history) == 1
        assert rule.history[0].success is True
