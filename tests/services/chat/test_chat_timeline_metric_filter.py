from __future__ import annotations

from datetime import datetime, timezone

import pytest

from vcenter_event_assistant.services.chat.chat_period_metrics import PeriodMetricBucketPoint, PeriodMetricHostSeries
from vcenter_event_assistant.services.chat.chat_timeline_metric_filter import build_timeline_metric_entries


def _point(avg: float) -> PeriodMetricBucketPoint:
    return PeriodMetricBucketPoint(
        bucket_start_utc=datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc),
        avg=avg,
        n=1,
    )


def test_build_timeline_metric_entries_filters_zero_and_negative_values() -> None:
    series = [
        PeriodMetricHostSeries(
            entity_name="esxi-01.example.local",
            entity_moid="host-1",
            metric_key="host.cpu.usage_pct",
            series=[_point(0.0), _point(-1.0), _point(12.34)],
        )
    ]

    rows = build_timeline_metric_entries(
        series,
        threshold_cpu_pct=None,
        threshold_memory_pct=None,
    )

    assert len(rows) == 1
    assert rows[0].title == "esxi-01 host.cpu.usage_pct: avg=12.34"


def test_build_timeline_metric_entries_applies_threshold_per_category() -> None:
    series = [
        PeriodMetricHostSeries(
            entity_name="esxi-01.example.local",
            entity_moid="host-1",
            metric_key="host.cpu.usage_pct",
            series=[_point(49.0), _point(50.0)],
        ),
        PeriodMetricHostSeries(
            entity_name="esxi-01.example.local",
            entity_moid="host-1",
            metric_key="host.mem.usage_pct",
            series=[_point(69.99), _point(70.0)],
        ),
    ]

    rows = build_timeline_metric_entries(
        series,
        threshold_cpu_pct=50.0,
        threshold_memory_pct=70.0,
    )

    titles = [row.title for row in rows]
    assert titles == [
        "esxi-01 host.cpu.usage_pct: avg=50.00",
        "esxi-01 host.mem.usage_pct: avg=70.00",
    ]


@pytest.mark.parametrize(
    "metric_key",
    [
        "host.disk.read_kbps",
        "host.disk.write_kbps",
        "host.disk.usage_pct",
        "host.net.bytes_rx_kbps",
        "host.net.bytes_tx_kbps",
        "host.net.usage_kbps",
    ],
)
def test_build_timeline_metric_entries_skips_disk_and_network_series(metric_key: str) -> None:
    """ディスクとネットワークは値が KB/s で、% の閾値で判定できないので項目にしない（Issue #316）。"""
    series = [
        PeriodMetricHostSeries(
            entity_name="esxi-01.example.local",
            entity_moid="host-1",
            metric_key=metric_key,
            series=[_point(0.5), _point(80.0), _point(250000.0)],
        )
    ]

    rows = build_timeline_metric_entries(
        series,
        threshold_cpu_pct=50.0,
        threshold_memory_pct=None,
    )

    assert rows == []


def test_build_timeline_metric_entries_uses_trimmed_host_when_not_fqdn() -> None:
    series = [
        PeriodMetricHostSeries(
            entity_name="  esxi-standalone  ",
            entity_moid="host-1",
            metric_key="host.cpu.usage_pct",
            series=[_point(10.0)],
        )
    ]

    rows = build_timeline_metric_entries(
        series,
        threshold_cpu_pct=None,
        threshold_memory_pct=None,
    )

    assert [row.title for row in rows] == ["esxi-standalone host.cpu.usage_pct: avg=10.00"]
