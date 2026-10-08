"""ホストメトリクス収集（perf）のユニットテスト。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pyVmomi import vim

from vcenter_event_assistant.collectors.perf import _host_is_connected, _host_metrics, sample_hosts_blocking


def _host(
    *,
    name: str,
    moid: str,
    connection_state,
    quick_stats,
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        _moId=moid,
        runtime=SimpleNamespace(connectionState=connection_state),
        summary=SimpleNamespace(
            quickStats=quick_stats,
            hardware=SimpleNamespace(cpuMhz=2000),
        ),
        hardware=SimpleNamespace(
            cpuInfo=SimpleNamespace(numCpuCores=4),
            memorySize=8 * 1024 * 1024 * 1024,
        ),
    )


def test_host_is_connected_requires_connected_state() -> None:
    connected = _host(
        name="ok",
        moid="host-1",
        connection_state=vim.HostSystem.ConnectionState.connected,
        quick_stats=SimpleNamespace(overallCpuUsage=1, overallMemoryUsage=1),
    )
    disconnected = _host(
        name="bad",
        moid="host-2",
        connection_state=vim.HostSystem.ConnectionState.disconnected,
        quick_stats=SimpleNamespace(overallCpuUsage=1, overallMemoryUsage=1),
    )
    assert _host_is_connected(connected) is True
    assert _host_is_connected(disconnected) is False


def test_host_metrics_skips_disconnected_and_missing_quick_stats() -> None:
    disconnected = _host(
        name="bad",
        moid="host-2",
        connection_state=vim.HostSystem.ConnectionState.disconnected,
        quick_stats=SimpleNamespace(overallCpuUsage=1, overallMemoryUsage=1),
    )
    no_stats = _host(
        name="nostats",
        moid="host-3",
        connection_state=vim.HostSystem.ConnectionState.connected,
        quick_stats=None,
    )
    assert _host_metrics(disconnected) == []
    assert _host_metrics(no_stats) == []


def test_sample_hosts_skips_failed_host_and_keeps_others() -> None:
    good = _host(
        name="good",
        moid="host-good",
        connection_state=vim.HostSystem.ConnectionState.connected,
        quick_stats=SimpleNamespace(overallCpuUsage=1000, overallMemoryUsage=1024),
    )
    bad = _host(
        name="bad",
        moid="host-bad",
        connection_state=vim.HostSystem.ConnectionState.connected,
        quick_stats=SimpleNamespace(overallCpuUsage=1000, overallMemoryUsage=1024),
    )

    si = MagicMock()

    with (
        patch(
            "vcenter_event_assistant.collectors.perf.connect_vcenter",
            return_value=si,
        ),
        patch("vcenter_event_assistant.collectors.perf.disconnect"),
        patch(
            "vcenter_event_assistant.collectors.perf._iter_hosts",
            return_value=[good, bad],
        ),
        patch(
            "vcenter_event_assistant.collectors.perf._host_metrics",
            side_effect=[
                [{"entity_moid": "host-good", "metric_key": "host.cpu.usage_pct", "value": 1.0}],
                RuntimeError("host unreachable"),
            ],
        ),
        patch(
            "vcenter_event_assistant.collectors.perf.collect_host_perf_metric_rows",
            return_value=[],
        ),
        patch(
            "vcenter_event_assistant.collectors.perf.sample_datastore_metrics_blocking",
            return_value=[],
        ),
    ):
        rows = sample_hosts_blocking(
            host="vc",
            port=443,
            username="u",
            password="p",
        )

    assert len(rows) == 1
    assert rows[0]["entity_moid"] == "host-good"
