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


def test_parse_perf_query_result_rows_sums_instances_and_maps_keys() -> None:
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
    by_key = {r["metric_key"]: r["value"] for r in rows}
    assert by_key["host.net.dropped_rx_total"] == 15.0
    assert by_key["host.disk.read_kbps"] == 3.25
    assert all(r["entity_type"] == "HostSystem" for r in rows)
    assert rows[0]["entity_moid"] == "host-1"


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

    avail_net = SimpleNamespace(counterId=101, instance="vmnic0")
    avail_disk = SimpleNamespace(counterId=202, instance="")

    ser_net = SimpleNamespace(
        id=SimpleNamespace(counterId=101, instance="vmnic0"),
        value=[7.0],
    )
    ser_disk = SimpleNamespace(
        id=SimpleNamespace(counterId=202, instance=""),
        value=[128.5],
    )
    pem = SimpleNamespace(value=[ser_net, ser_disk])

    perf_manager = MagicMock()
    perf_manager.perfCounter = [counter_net, counter_disk]
    perf_manager.QueryPerfProviderSummary.return_value = SimpleNamespace(refreshRate=20)
    perf_manager.QueryAvailablePerfMetric.return_value = [avail_net, avail_disk]
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
    by_key = {r["metric_key"]: r["value"] for r in rows}
    assert by_key["host.net.dropped_rx_total"] == 7.0
    assert by_key["host.disk.read_kbps"] == 128.5


def test_collect_host_perf_metric_rows_returns_empty_on_query_failure() -> None:
    perf_manager = MagicMock()
    perf_manager.perfCounter = []
    content = SimpleNamespace(perfManager=perf_manager)
    si = SimpleNamespace()
    si.RetrieveContent = MagicMock(return_value=content)
    host = SimpleNamespace(_moId="m", name="h")
    rows = collect_host_perf_metric_rows(si, host)
    assert rows == []
