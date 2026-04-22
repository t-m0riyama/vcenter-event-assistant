import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
from vcenter_event_assistant.db.models import AlertRule, AlertState, EventRecord, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alert_eval import AlertEvaluator

@pytest.mark.asyncio
async def test_evaluate_event_score_firing():
    # テストデータの準備
    async with session_scope() as session:
        # VCenter がないと FK 制約でエラーになる可能性があるため作成
        vc = VCenter(name="vc1", host="vc1", username="u", password="p")
        session.add(vc)
        await session.flush()
        
        # ルールの作成: スコア 60 以上で発火
        rule = AlertRule(
            name="High Score Event",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 5}
        )
        session.add(rule)
        
        # 閾値超えのイベント
        event = EventRecord(
            vcenter_id=vc.id,
            occurred_at=datetime.now(timezone.utc),
            event_type="HostConnectionLostEvent",
            vmware_key=1,
            notable_score=70
        )
        session.add(event)
        await session.flush()
        rule_id = rule.id

    # 評価の実行
    evaluator = AlertEvaluator()
    # 実際の実装では _notify 内で DB セッションを別途開くため、内部メソッドをパッチする
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.called
        
    # 状態が更新されたか
    async with session_scope() as session:
        from sqlalchemy import select
        res = await session.execute(
            select(AlertState).where(AlertState.rule_id == rule_id)
        )
        state = res.scalar_one()
        assert state.state == "firing"
        assert state.context_key == "HostConnectionLostEvent"

@pytest.mark.asyncio
async def test_evaluate_event_score_resolution():
    async with session_scope() as session:
        vc = VCenter(name="vc2", host="vc2", username="u", password="p")
        session.add(vc)
        await session.flush()
        
        rule = AlertRule(
            name="Cooldown Test",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 5}
        )
        session.add(rule)
        await session.flush()
        rule_id = rule.id
        
        # すでに発火状態
        state = AlertState(
            rule_id=rule.id,
            state="firing",
            context_key="SomeEvent",
            fired_at=datetime.now(timezone.utc) - timedelta(minutes=10) # 10分前（クールダウン5分より前）
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
