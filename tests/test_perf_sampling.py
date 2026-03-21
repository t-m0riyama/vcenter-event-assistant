"""Tests for perf.sample_hosts_blocking wiring."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from vcenter_event_assistant.collectors.perf import sample_hosts_blocking


@patch("vcenter_event_assistant.collectors.perf.disconnect")
@patch("vcenter_event_assistant.collectors.perf.sample_datastore_metrics_blocking")
@patch("vcenter_event_assistant.collectors.perf.collect_host_perf_metric_rows")
@patch("vcenter_event_assistant.collectors.perf._iter_hosts")
@patch("vcenter_event_assistant.collectors.perf.connect_vcenter")
def test_sample_hosts_blocking_merges_cpu_mem_host_perf_and_datastore(
    mock_connect: MagicMock,
    mock_iter_hosts: MagicMock,
    mock_host_perf: MagicMock,
    mock_ds: MagicMock,
    mock_disconnect: MagicMock,
) -> None:
    si = object()
    mock_connect.return_value = si
    host = SimpleNamespace(
        _moId="host-1",
        name="esxi-a",
        summary=SimpleNamespace(
            quickStats=SimpleNamespace(overallCpuUsage=1000, overallMemoryUsage=1024),
            hardware=SimpleNamespace(cpuMhz=2000),
        ),
        hardware=SimpleNamespace(
            cpuInfo=SimpleNamespace(numCpuCores=4),
            memorySize=8 * 1024**3,
        ),
    )
    mock_iter_hosts.return_value = [host]
    mock_host_perf.return_value = [
        {
            "metric_key": "host.net.bytes_rx_kbps",
            "value": 1.0,
            "sampled_at": datetime.now(timezone.utc),
            "entity_type": "HostSystem",
            "entity_moid": "host-1",
            "entity_name": "esxi-a",
        }
    ]
    mock_ds.return_value = [
        {
            "metric_key": "datastore.space.used_pct",
            "value": 50.0,
            "sampled_at": datetime.now(timezone.utc),
            "entity_type": "Datastore",
            "entity_moid": "ds-1",
            "entity_name": "DS1",
        }
    ]

    rows = sample_hosts_blocking(host="vc.example", port=443, username="u", password="p")

    keys = {r["metric_key"] for r in rows}
    assert "host.cpu.usage_pct" in keys
    assert "host.mem.usage_pct" in keys
    assert "host.net.bytes_rx_kbps" in keys
    assert "datastore.space.used_pct" in keys
    mock_host_perf.assert_called_once_with(si, host)
    mock_ds.assert_called_once_with(si)
    mock_disconnect.assert_called_once_with(si)
