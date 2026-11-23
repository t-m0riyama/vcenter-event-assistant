"""障害パターンの通知と状態遷移。"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from vcenter_event_assistant.db.models import (
    AlertHistory,
    AlertNotificationOutbox,
    AlertRule,
    AlertState,
    EventEntity,
    EventRecord,
    IncidentTimelineManualSnapshot,
    VCenter,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alerting.alert_eval import AlertEvaluator
from vcenter_event_assistant.services.alerting.notification_outbox import deliver_notifications
from vcenter_event_assistant.services.event_patterns import query
from vcenter_event_assistant.settings import get_settings

_PATTERN = "host-conn-flapping"
_MOID = "host:" + "a" * 251
_DISCONNECT = "vim.event.HostConnectionLostEvent"
_RECONNECT_FAILED = "vim.event.HostReconnectionFailedEvent"


async def _add_events(vid, *events, entity_name="ESXi"):
    async with session_scope() as session:
        for key, at, event_type in events:
            session.add(EventRecord(
                vcenter_id=vid, vmware_key=key, occurred_at=at, event_type=event_type,
                entities=[EventEntity(
                    vcenter_id=vid, role="host", position=0, is_primary=True,
                    entity_moid=_MOID, entity_name=entity_name, entity_type="HostSystem",
                )],
            ))


async def _setup(pattern_ids):
    async with session_scope() as session:
        vc = VCenter(name="vc-pattern", host="vc-pattern", username="u", password="p")
        rule = AlertRule(
            name="繰り返し", rule_type="event_pattern", alert_level="warning",
            config={"pattern_ids": pattern_ids, "cooldown_minutes": 10},
        )
        session.add_all([vc, rule])
        await session.flush()
        return vc.id, rule.id


async def _state():
    async with session_scope() as session:
        return (await session.scalars(select(AlertState))).one()


@pytest.mark.asyncio
async def test_event_pattern_fires_absorbs_and_renotifies_then_resolves(client):
    vid, rule_id = await _setup([_PATTERN])
    now = datetime.now(timezone.utc)
    times = [now - timedelta(minutes=m) for m in (65, 45, 25, 20, 15, 10, 5)]
    await _add_events(
        vid, *((i, at, _DISCONNECT) for i, at in enumerate(times[:3])),
        (100, times[3], _RECONNECT_FAILED),
    )
    await _add_events(vid, (101, times[3], "vim.event.HostRenamedEvent"), entity_name="ESXi-renamed")
    settings = get_settings().model_copy(update={"alert_event_eval_lookback_hours": 1, "mock_mode": True})
    evaluator = AlertEvaluator(settings)
    key = f"{vid}:{_MOID}:{_PATTERN}"
    assert (await evaluator.evaluate_all()).firings == 1
    async with session_scope() as session:
        outbox = (await session.scalars(select(AlertNotificationOutbox))).one()
        for value in (
            "ホストの切断の繰り返し (エラー)", "ESXi-renamed", _MOID, "vc-pattern",
            times[0].isoformat(), times[2].isoformat(), "件数: 3", "管理ネットワーク",
        ):
            assert value in outbox.body
        assert outbox.notification["alert_level"] == "warning"
    await deliver_notifications(settings)
    async with session_scope() as session:
        snapshot = (await session.scalars(select(IncidentTimelineManualSnapshot))).one()
        assert len(snapshot.trigger_id) == 128

    await _add_events(vid, (3, times[3], _DISCONNECT))
    assert (await evaluator.evaluate_all()).firings == 0
    history = (await client.get("/api/alerts/history")).json()["items"]
    assert history[0]["entity_name"] == "ESXi"
    assert "ESXi-renamed" in outbox.body
    state = await _state()
    assert state.fired_at.replace(tzinfo=timezone.utc) == times[3]
    async with session_scope() as session:
        state = await session.get(AlertState, state.id)
        state.last_notified_at = now - timedelta(minutes=11)
    assert (await evaluator.evaluate_all()).firings == 0
    await _add_events(vid, (4, times[4], _DISCONNECT))
    assert (await evaluator.evaluate_all()).firings == 1

    history = (await client.get("/api/alerts/history")).json()["items"]
    assert all(item["can_resolve"] for item in history)
    assert (await client.post("/api/alerts/states/resolve", json={
        "rule_id": rule_id, "context_key": key,
    })).status_code == 204
    assert (await evaluator.evaluate_all()).firings == 0
    assert (await _state()).state == "resolved"
    assert (await _state()).fired_at.replace(tzinfo=timezone.utc) == times[4]
    await _add_events(vid, (5, times[5], _DISCONNECT))
    assert (await evaluator.evaluate_all()).firings == 1
    # 保存期間から外れたイベントを模す。
    async with session_scope() as session:
        await session.execute(delete(EventRecord))
    summary = await evaluator.evaluate_all()
    assert (summary.firings, summary.resolutions) == (0, 1)
    assert (await _state()).state == "resolved"
    assert (await _state()).fired_at.replace(tzinfo=timezone.utc) == times[5]
    async with session_scope() as session:
        history = (await session.scalars(select(AlertHistory).order_by(AlertHistory.id))).all()
        assert [row.state for row in history] == ["firing", "firing", "resolved", "firing"]


@pytest.mark.asyncio
async def test_event_pattern_omitted_unknown_and_removed_keep_distinct_states(monkeypatch, caplog):
    vid, rule_id = await _setup([])
    now = datetime.now(timezone.utc)
    await _add_events(vid, *(
        (i, now - timedelta(minutes=10 - i), _DISCONNECT) for i in range(3)
    ))
    evaluator = AlertEvaluator(get_settings())
    assert (await evaluator.evaluate_all()).firings == 1
    monkeypatch.setattr(query, "PATTERN_ROW_LIMIT", 2)
    assert (await evaluator.evaluate_all()).resolutions == 0
    assert (await _state()).state == "firing"
    assert "host-conn-flapping" in caplog.text
    async with session_scope() as session:
        rule = await session.get(AlertRule, rule_id)
        rule.config = {"pattern_ids": ["removed-in-code", "apd-timeout"]}
        session.add(AlertState(
            rule_id=rule_id, context_key=f"{vid}:{_MOID}:removed-in-code",
            state="firing", fired_at=now,
        ))
    assert (await evaluator.evaluate_all()).resolutions == 1
    assert "removed-in-code" in caplog.text
    async with session_scope() as session:
        states = (await session.scalars(select(AlertState).order_by(AlertState.id))).all()
        assert [state.state for state in states] == ["resolved", "firing"]
        history = (await session.scalars(select(AlertHistory))).all()
        assert [row.state for row in history] == ["firing"]


@pytest.mark.asyncio
async def test_event_pattern_notification_uses_detection_name_when_latest_name_is_missing():
    vid, _ = await _setup([_PATTERN])
    now = datetime.now(timezone.utc)
    await _add_events(
        vid, *((i, now - timedelta(minutes=10 - i), _DISCONNECT) for i in range(3)),
    )
    await _add_events(vid, (100, now - timedelta(minutes=1), "OtherEvent"), entity_name=None)
    evaluator = AlertEvaluator(get_settings().model_copy(update={"mock_mode": True}))
    assert (await evaluator.evaluate_all()).firings == 1
    async with session_scope() as session:
        outbox = (await session.scalars(select(AlertNotificationOutbox))).one()
        assert f"対象: ESXi ({_MOID})" in outbox.body


@pytest.mark.asyncio
async def test_event_pattern_manual_resolution_isolated_by_rule_id_for_same_key(client):
    vid, all_id = await _setup([])
    created = await client.post("/api/alerts/rules", json={
        "name": "個別のパターン", "rule_type": "event_pattern", "alert_level": "error",
        "config": {"pattern_ids": [_PATTERN]},
    })
    assert created.status_code == 201
    other_id = created.json()["id"]
    now = datetime.now(timezone.utc)
    await _add_events(
        vid, *((i, now - timedelta(minutes=10 - i), _DISCONNECT) for i in range(3)),
    )
    evaluator = AlertEvaluator(get_settings())
    key = f"{vid}:{_MOID}:{_PATTERN}"
    assert (await evaluator.evaluate_all()).firings == 2

    async def states_and_history():
        async with session_scope() as session:
            states = {s.rule_id: s for s in await session.scalars(select(AlertState))}
        history = (await client.get("/api/alerts/history")).json()["items"]
        return states, [row for row in history if row["rule_id"] == other_id]

    before, other_history_before = await states_and_history()
    assert {rule_id: (s.context_key, s.state) for rule_id, s in before.items()} == {
        all_id: (key, "firing"), other_id: (key, "firing"),
    }
    assert len(other_history_before) == 1
    assert (await client.post("/api/alerts/states/resolve", json={
        "rule_id": all_id, "context_key": key,
    })).status_code == 204
    assert (await evaluator.evaluate_all()).firings == 0
    after, other_history_after = await states_and_history()
    assert after[all_id].state == "resolved"
    assert after[other_id].state == "firing"
    assert after[other_id].fired_at == before[other_id].fired_at
    assert other_history_after == other_history_before
