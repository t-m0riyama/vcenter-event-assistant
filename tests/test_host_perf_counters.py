"""Tests for host PerformanceManager metric collection."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pyVmomi import vim

from vcenter_event_assistant.collectors.host_perf_counters import (
    collect_host_perf_metric_rows,
    parse_perf_query_result_rows,
)
from vcenter_event_assistant.collectors import host_perf_counters as hpc


def test_parse_perf_query_result_rows_splits_instances_and_maps_keys() -> None:
    sampled = datetime(2026, 3, 22, 12, 0, 0, tzinfo=timezone.utc)
    s1 = SimpleNamespace(id=SimpleNamespace(counterId=101, instance="vmnic0"), value=[10.0])
    s2 = SimpleNamespace(id=SimpleNamespace(counterId=101, instance="vmnic1"), value=[5.0])
    s3 = SimpleNamespace(id=SimpleNamespace(counterId=202, instance=""), value=[3.25])
    pem = SimpleNamespace(value=[s1, s2, s3])
    rows = parse_perf_query_result_rows(
        entity_moid="host-1",
        entity_name="esxi1",
        sampled_at=sampled,
        perf_entity_metrics=[pem],
        counter_id_to_metric_key={
            101: "host.net.dropped_rx_total",
            202: "host.disk.read_kbps",
        },
    )
    assert len(rows) == 3
    assert all(r["entity_type"] == "HostSystem" for r in rows)
    net_rows = [r for r in rows if r["metric_key"] == "host.net.dropped_rx_total"]
    assert len(net_rows) == 2
    net_by_moid = {r["entity_moid"]: r for r in net_rows}
    assert net_by_moid["host-1:vmnic0"]["value"] == 10.0
    assert net_by_moid["host-1:vmnic1"]["value"] == 5.0
    assert net_by_moid["host-1:vmnic0"]["entity_name"] == "esxi1 / vmnic0"
    disk_rows = [r for r in rows if r["metric_key"] == "host.disk.read_kbps"]
    assert len(disk_rows) == 1
    assert disk_rows[0]["value"] == 3.25
    assert disk_rows[0]["entity_moid"] == "host-1"
    assert disk_rows[0]["entity_name"] == "esxi1"


def test_collect_host_perf_metric_rows_returns_rows_when_query_perf_succeeds() -> None:
    """Integration-style test with mocked ServiceInstance and PerformanceManager."""
    now = datetime.now(timezone.utc)

    counter_net = SimpleNamespace(
        key=101,
        groupInfo=SimpleNamespace(key="net"),
        nameInfo=SimpleNamespace(key="droppedRx"),
        rollupType=vim.PerformanceManager.CounterInfo.RollupType.summation,
    )
    counter_disk = SimpleNamespace(
        key=202,
        groupInfo=SimpleNamespace(key="disk"),
        nameInfo=SimpleNamespace(key="read"),
        rollupType=vim.PerformanceManager.CounterInfo.RollupType.average,
    )

    avail_net0 = SimpleNamespace(counterId=101, instance="vmnic0")
    avail_net1 = SimpleNamespace(counterId=101, instance="vmnic1")
    avail_disk = SimpleNamespace(counterId=202, instance="")

    ser_net0 = SimpleNamespace(
        id=SimpleNamespace(counterId=101, instance="vmnic0"),
        value=[7.0],
    )
    ser_net1 = SimpleNamespace(
        id=SimpleNamespace(counterId=101, instance="vmnic1"),
        value=[3.0],
    )
    ser_disk = SimpleNamespace(
        id=SimpleNamespace(counterId=202, instance=""),
        value=[128.5],
    )
    pem = SimpleNamespace(value=[ser_net0, ser_net1, ser_disk])

    perf_manager = MagicMock()
    perf_manager.perfCounter = [counter_net, counter_disk]
    perf_manager.QueryPerfProviderSummary.return_value = SimpleNamespace(refreshRate=20)
    perf_manager.QueryAvailablePerfMetric.return_value = [avail_net0, avail_net1, avail_disk]
    perf_manager.QueryPerf.return_value = [pem]

    content = SimpleNamespace(perfManager=perf_manager)
    si = SimpleNamespace()
    si.RetrieveContent = MagicMock(return_value=content)

    host = SimpleNamespace(_moId="moid-9", name="h9")

    mock_spec = MagicMock()
    with (
        patch.object(hpc, "datetime") as mock_dt,
        patch.object(hpc.vim, "PerfQuerySpec", return_value=mock_spec),
    ):
        mock_dt.now = MagicMock(return_value=now)
        rows = collect_host_perf_metric_rows(si, host)

    keys = {r["metric_key"] for r in rows}
    assert "host.net.dropped_rx_total" in keys
    assert "host.disk.read_kbps" in keys
    assert len(rows) == 3
    net_rows = [r for r in rows if r["metric_key"] == "host.net.dropped_rx_total"]
    assert len(net_rows) == 2
    assert {r["entity_moid"] for r in net_rows} == {"moid-9:vmnic0", "moid-9:vmnic1"}
    by_net = {r["entity_moid"]: r["value"] for r in net_rows}
    assert by_net["moid-9:vmnic0"] == 7.0
    assert by_net["moid-9:vmnic1"] == 3.0
    disk_rows = [r for r in rows if r["metric_key"] == "host.disk.read_kbps"]
    assert len(disk_rows) == 1
    assert disk_rows[0]["value"] == 128.5
    assert disk_rows[0]["entity_moid"] == "moid-9"


def test_collect_host_perf_metric_rows_returns_empty_on_query_failure() -> None:
    perf_manager = MagicMock()
    perf_manager.perfCounter = []
    content = SimpleNamespace(perfManager=perf_manager)
    si = SimpleNamespace()
    si.RetrieveContent = MagicMock(return_value=content)
    host = SimpleNamespace(_moId="m", name="h")
    rows = collect_host_perf_metric_rows(si, host)
    assert rows == []
