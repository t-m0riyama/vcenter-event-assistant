"""digest_context.build_digest_context の集約テスト。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from vcenter_event_assistant.db.models import EventRecord, MetricSample, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.digest_context import build_digest_context


@pytest.mark.asyncio
async def test_build_digest_context_counts_and_top_rows() -> None:
    vid = uuid.uuid4()
    base = datetime(2026, 3, 22, 12, 0, 0, tzinfo=timezone.utc)
    window_start = base - timedelta(hours=1)
    window_end = base + timedelta(hours=1)

    async with session_scope() as session:
        session.add(
            VCenter(
                id=vid,
                name="ctx-vc",
                host="h",
                port=443,
                username="u",
                password="p",
                is_enabled=True,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=base,
                event_type="VmPoweredOnEvent",
                message="a",
                severity="info",
                vmware_key=1,
                notable_score=5,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=base + timedelta(minutes=1),
                event_type="HostConnectionLostEvent",
                message="fail host",
                severity="error",
                vmware_key=2,
                notable_score=75,
            )
        )
        session.add(
            MetricSample(
                vcenter_id=vid,
                sampled_at=base,
                entity_type="HostSystem",
                entity_moid="moid-1",
                entity_name="esxi-1",
                metric_key="host.cpu.usage_pct",
                value=88.5,
            )
        )

    async with session_scope() as session:
        ctx = await build_digest_context(session, window_start, window_end, top_notable_min_score=1)

    assert ctx.total_events == 2
    assert ctx.notable_events_count == 1
    assert len(ctx.top_notable_events) >= 1
    assert ctx.top_notable_events[0].event_type == "HostConnectionLostEvent"
    assert ctx.top_notable_events[0].notable_score == 75
    assert len(ctx.high_cpu_hosts) == 1
    assert ctx.high_cpu_hosts[0].entity_name == "esxi-1"
    assert abs(ctx.high_cpu_hosts[0].value - 88.5) < 0.01


@pytest.mark.asyncio
async def test_build_digest_context_rejects_inverted_window() -> None:
    a = datetime(2026, 1, 1, tzinfo=timezone.utc)
    b = datetime(2026, 1, 2, tzinfo=timezone.utc)
    async with session_scope() as session:
        with pytest.raises(ValueError, match="from_utc"):
            await build_digest_context(session, b, a)
