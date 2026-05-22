"""incident_timeline_snapshot サービスのテスト。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from vcenter_event_assistant.db.models import (
    AlertRule,
    AlertState,
    EventRecord,
    IncidentTimelineManualSnapshot,
    VCenter,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alert_eval import AlertEvaluator
from vcenter_event_assistant.services.incident_timeline_snapshot import (
    build_alert_rule_snapshot_build_request,
    format_alert_rule_trigger_id,
    persist_alert_rule_firing_snapshot,
    slug_alert_context_key,
)


def test_slug_alert_context_key_normalizes_moid():
    assert slug_alert_context_key("host-1") == "host_1"


def test_build_alert_rule_snapshot_build_request_lookback():
    fired_at = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    now = datetime(2026, 5, 22, 14, 0, tzinfo=timezone.utc)
    req = build_alert_rule_snapshot_build_request(
        fired_at=fired_at,
        to_time=now,
        lookback_hours=2,
    )
    assert req.from_time == fired_at - timedelta(hours=2)
    assert req.to_time == now
    assert req.include_period_metrics_cpu is True
    assert req.include_period_metrics_memory is True
    assert req.alert_top_n == 7


def test_format_alert_rule_trigger_id():
    assert format_alert_rule_trigger_id(rule_id=3, context_key="host-1") == "alert_rule_3_host_1"


@pytest.mark.asyncio
async def test_persist_alert_rule_firing_snapshot_inserts_once():
    fired_at = datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc)
    to_time = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    rule = AlertRule(name="CPU High", rule_type="metric_threshold", config={"metric_key": "cpu", "threshold": 90})

    async with session_scope() as session:
        session.add(rule)
        await session.flush()
        state = AlertState(
            rule_id=rule.id,
            state="firing",
            context_key="host-1",
            fired_at=fired_at,
        )
        await persist_alert_rule_firing_snapshot(
            session=session,
            rule=rule,
            state=state,
            details="Metric cpu reached 95",
            to_time=to_time,
            lookback_hours=2,
        )
        await persist_alert_rule_firing_snapshot(
            session=session,
            rule=rule,
            state=state,
            details="Metric cpu reached 95",
            to_time=to_time,
            lookback_hours=2,
        )
        await session.commit()

    async with session_scope() as session:
        res = await session.execute(
            select(IncidentTimelineManualSnapshot).where(
                IncidentTimelineManualSnapshot.snapshot_kind == "auto",
            )
        )
        rows = res.scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.trigger_id == "alert_rule_1_host_1"
        assert row.trigger_evidence["trigger_type"] == "alert_rule"
        assert row.operator_note.startswith("自動スナップショット:")
        assert row.build_request_payload["include_period_metrics_cpu"] is True


@pytest.mark.asyncio
async def test_persist_alert_rule_firing_snapshot_skips_resolved():
    fired_at = datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc)
    rule = AlertRule(name="CPU High", rule_type="metric_threshold", config={})

    async with session_scope() as session:
        session.add(rule)
        await session.flush()
        state = AlertState(
            rule_id=rule.id,
            state="resolved",
            context_key="host-1",
            fired_at=fired_at,
        )
        await persist_alert_rule_firing_snapshot(
            session=session,
            rule=rule,
            state=state,
            details="resolved",
            to_time=datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc),
            lookback_hours=2,
        )
        await session.commit()

    async with session_scope() as session:
        res = await session.execute(select(IncidentTimelineManualSnapshot))
        assert len(res.scalars().all()) == 0


@pytest.mark.asyncio
async def test_evaluate_event_score_firing_persists_auto_snapshot():
    async with session_scope() as session:
        vc = VCenter(name="vc_snap", host="vc_snap", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="High Score Snapshot",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 5},
        )
        session.add(rule)
        event = EventRecord(
            vcenter_id=vc.id,
            occurred_at=datetime(2026, 5, 22, 8, 0, tzinfo=timezone.utc),
            event_type="HostConnectionLostEvent",
            vmware_key=99,
            notable_score=70,
        )
        session.add(event)
        await session.flush()

    evaluator = AlertEvaluator()
    with patch.object(evaluator.email_channel, "notify", new_callable=AsyncMock):
        await evaluator.evaluate_all()

    async with session_scope() as session:
        res = await session.execute(
            select(IncidentTimelineManualSnapshot).where(
                IncidentTimelineManualSnapshot.snapshot_kind == "auto",
            )
        )
        rows = res.scalars().all()
        assert len(rows) == 1
        assert rows[0].trigger_id.startswith("alert_rule_")
        assert rows[0].trigger_evidence["trigger_type"] == "alert_rule"


@pytest.mark.asyncio
async def test_evaluate_event_score_resolution_does_not_add_snapshot():
    async with session_scope() as session:
        vc = VCenter(name="vc_res", host="vc_res", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Cooldown Snapshot",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 5},
        )
        session.add(rule)
        await session.flush()
        state = AlertState(
            rule_id=rule.id,
            state="firing",
            context_key="SomeEvent",
            fired_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        session.add(state)
        await session.flush()

    evaluator = AlertEvaluator()
    with patch.object(evaluator.email_channel, "notify", new_callable=AsyncMock):
        await evaluator.evaluate_all()

    async with session_scope() as session:
        res = await session.execute(
            select(IncidentTimelineManualSnapshot).where(
                IncidentTimelineManualSnapshot.snapshot_kind == "auto",
            )
        )
        assert len(res.scalars().all()) == 0
