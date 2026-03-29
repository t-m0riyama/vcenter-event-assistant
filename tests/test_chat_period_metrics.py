"""chat_period_metrics.build_chat_period_metrics の集計テスト。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from vcenter_event_assistant.db.models import MetricSample, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.chat_period_metrics import (
    PeriodMetricsPayload,
    build_chat_period_metrics,
)


@pytest.mark.asyncio
async def test_build_chat_period_metrics_returns_none_when_all_toggles_off() -> None:
    """4 トグルすべてオフのとき None。"""
    t0 = datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=1)
    async with session_scope() as session:
        out = await build_chat_period_metrics(
            session,
            t0,
            t1,
            vcenter_id=None,
            include_cpu=False,
            include_memory=False,
            include_disk_io=False,
            include_network_io=False,
        )
    assert out is None


@pytest.mark.asyncio
async def test_build_chat_period_metrics_rejects_inverted_range() -> None:
    t0 = datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
    async with session_scope() as session:
        with pytest.raises(ValueError, match="from_utc"):
            await build_chat_period_metrics(
                session,
                t0,
                t0,
                vcenter_id=None,
                include_cpu=True,
                include_memory=False,
                include_disk_io=False,
                include_network_io=False,
            )


@pytest.mark.asyncio
async def test_build_chat_period_metrics_cpu_bucket_averages_two_samples_same_bucket() -> None:
    """同一バケット内 2 サンプルの算術平均。"""
    vid = uuid.uuid4()
    host = "esxi-1"
    from_utc = datetime(2026, 3, 22, 10, 0, 0, tzinfo=timezone.utc)
    to_utc = from_utc + timedelta(hours=2)
    # 期間 2h → バケット 15 分。+5 分と +10 分は同一バケット
    t_a = from_utc + timedelta(minutes=5)
    t_b = from_utc + timedelta(minutes=10)

    async with session_scope() as session:
        session.add(
            VCenter(
                id=vid,
                name="vc",
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
                sampled_at=t_a,
                entity_type="HostSystem",
                entity_moid="m1",
                entity_name=host,
                metric_key="host.cpu.usage_pct",
                value=40.0,
            )
        )
        session.add(
            MetricSample(
                vcenter_id=vid,
                sampled_at=t_b,
                entity_type="HostSystem",
                entity_moid="m1",
                entity_name=host,
                metric_key="host.cpu.usage_pct",
                value=60.0,
            )
        )

    async with session_scope() as session:
        out = await build_chat_period_metrics(
            session,
            from_utc,
            to_utc,
            vcenter_id=None,
            include_cpu=True,
            include_memory=False,
            include_disk_io=False,
            include_network_io=False,
            max_buckets=48,
            max_hosts_per_category=15,
        )

    assert out is not None
    assert isinstance(out, PeriodMetricsPayload)
    assert out.cpu is not None
    assert len(out.cpu) == 1
    assert out.cpu[0].entity_name == host
    assert len(out.cpu[0].series) == 1
    pt = out.cpu[0].series[0]
    assert abs(pt.avg - 50.0) < 0.01
    assert pt.n == 2
    assert out.memory is None
    assert out.disk is None
    assert out.network is None


@pytest.mark.asyncio
async def test_build_chat_period_metrics_cpu_only_on_does_not_include_memory_key() -> None:
    """CPU のみ ON のとき memory セクションが無い。"""
    vid = uuid.uuid4()
    from_utc = datetime(2026, 3, 22, 10, 0, 0, tzinfo=timezone.utc)
    to_utc = from_utc + timedelta(hours=1)

    async with session_scope() as session:
        session.add(
            VCenter(
                id=vid,
                name="vc",
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
                sampled_at=from_utc + timedelta(minutes=5),
                entity_type="HostSystem",
                entity_moid="m1",
                entity_name="h1",
                metric_key="host.cpu.usage_pct",
                value=10.0,
            )
        )
        session.add(
            MetricSample(
                vcenter_id=vid,
                sampled_at=from_utc + timedelta(minutes=5),
                entity_type="HostSystem",
                entity_moid="m1",
                entity_name="h1",
                metric_key="host.mem.usage_pct",
                value=80.0,
            )
        )

    async with session_scope() as session:
        out = await build_chat_period_metrics(
            session,
            from_utc,
            to_utc,
            vcenter_id=None,
            include_cpu=True,
            include_memory=False,
            include_disk_io=False,
            include_network_io=False,
        )

    assert out is not None
    assert out.cpu is not None
    assert out.memory is None
