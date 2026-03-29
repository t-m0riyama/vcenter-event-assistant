"""correlation_context.build_cpu_event_correlation の集計テスト。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from vcenter_event_assistant.db.models import EventRecord, MetricSample, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.correlation_context import build_cpu_event_correlation


@pytest.mark.asyncio
async def test_build_cpu_event_correlation_counts_events_in_window() -> None:
    """閾値超え CPU アンカー周辺の同一ホストイベントのみ種別集計する。"""
    vid = uuid.uuid4()
    host = "esxi-anchor"
    anchor_t = datetime(2026, 3, 22, 12, 0, 0, tzinfo=timezone.utc)
    from_utc = anchor_t - timedelta(hours=2)
    to_utc = anchor_t + timedelta(hours=2)

    async with session_scope() as session:
        session.add(
            VCenter(
                id=vid,
                name="corr-vc",
                host="h",
                port=443,
                username="u",
                password="p",
                is_enabled=True,
            )
        )
        session.add(
            MetricSample(
                vcenter_id=vid,
                sampled_at=anchor_t,
                entity_type="HostSystem",
                entity_moid="host-moid-1",
                entity_name=host,
                metric_key="host.cpu.usage_pct",
                value=92.0,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=anchor_t + timedelta(minutes=5),
                event_type="TypeA",
                message="in window 1",
                severity="info",
                entity_name=host,
                vmware_key=101,
                notable_score=1,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=anchor_t + timedelta(minutes=8),
                event_type="TypeB",
                message="in window 2",
                severity="info",
                entity_name=host,
                vmware_key=102,
                notable_score=1,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=anchor_t + timedelta(hours=3),
                event_type="TypeZ",
                message="out of window",
                severity="info",
                entity_name=host,
                vmware_key=103,
                notable_score=1,
            )
        )

    async with session_scope() as session:
        payload = await build_cpu_event_correlation(
            session,
            from_utc,
            to_utc,
            vcenter_id=None,
            threshold_pct=85.0,
            window_minutes=15,
            max_anchors=20,
        )

    assert payload.anchor_selection == "threshold_met"
    assert len(payload.rows) == 1
    row = payload.rows[0]
    assert row.host == host
    assert abs(row.cpu_at_anchor - 92.0) < 0.01
    by_type = {e.event_type: e.count for e in row.events_in_window}
    assert by_type.get("TypeA") == 1
    assert by_type.get("TypeB") == 1
    assert "TypeZ" not in by_type


@pytest.mark.asyncio
async def test_build_cpu_event_correlation_falls_back_to_per_host_peak_when_below_threshold() -> None:
    """閾値未満しか無いとき digest と同様のホスト別ピークでアンカーにする。"""
    vid = uuid.uuid4()
    host = "esxi-below-threshold"
    anchor_t = datetime(2026, 3, 22, 12, 0, 0, tzinfo=timezone.utc)
    from_utc = anchor_t - timedelta(hours=2)
    to_utc = anchor_t + timedelta(hours=2)

    async with session_scope() as session:
        session.add(
            VCenter(
                id=vid,
                name="corr-vc",
                host="h",
                port=443,
                username="u",
                password="p",
                is_enabled=True,
            )
        )
        session.add(
            MetricSample(
                vcenter_id=vid,
                sampled_at=anchor_t,
                entity_type="HostSystem",
                entity_moid="host-moid-low",
                entity_name=host,
                metric_key="host.cpu.usage_pct",
                value=55.0,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=anchor_t + timedelta(minutes=5),
                event_type="LowCpuEvent",
                message="a",
                severity="info",
                entity_name=host,
                vmware_key=201,
                notable_score=1,
            )
        )

    async with session_scope() as session:
        payload = await build_cpu_event_correlation(
            session,
            from_utc,
            to_utc,
            vcenter_id=None,
            threshold_pct=85.0,
            window_minutes=15,
            max_anchors=20,
        )

    assert payload.anchor_selection == "per_host_peak_fallback"
    assert len(payload.rows) == 1
    assert payload.rows[0].host == host
    assert abs(payload.rows[0].cpu_at_anchor - 55.0) < 0.01
    assert any(e.event_type == "LowCpuEvent" for e in payload.rows[0].events_in_window)
