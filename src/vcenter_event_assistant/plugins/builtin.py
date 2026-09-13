"""Built-in collectors exposed through the same contract as external plugins."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from vcenter_event_assistant_plugin_api import (
    CollectionBatch,
    CollectionContext,
    CollectorManifest,
    EventInput,
    MetricDefinition,
    MetricSampleInput,
)
from vcenter_event_assistant_plugin_api.blocking import run_blocking


def _metric(row: dict[str, Any]) -> MetricSampleInput:
    return MetricSampleInput(
        sampled_at=row["sampled_at"],
        entity_type=row["entity_type"],
        entity_moid=row["entity_moid"],
        entity_name=row["entity_name"],
        metric_key=row["metric_key"],
        value=float(row["value"]),
    )


# plugin-api 側の実装をそのまま使う。プラグイン作者にも同じものが公開されている。
# 名前を残しているのは、テストが `@patch("...builtin._run_blocking")` のように
# ドット文字列でこのモジュール属性を差し替えているため。
_run_blocking = run_blocking


class _BaseCollector:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class EventsCollector(_BaseCollector):
    manifest = CollectorManifest(
        id="builtin.vcenter.events",
        display_name="vCenter Events",
        version="1.0.0",
        data_kinds=frozenset({"event"}),
        default_interval_seconds=120,
    )

    async def collect(self, context: CollectionContext) -> CollectionBatch:
        since = (
            datetime.fromisoformat(context.previous_cursor)
            if context.previous_cursor
            else None
        )
        fetch_since = since - timedelta(seconds=1) if since else None
        if context.mock_mode:
            from vcenter_event_assistant.mocks.mock_collectors import (
                fetch_mock_events_blocking,
            )

            rows, max_ts = await _run_blocking(
                fetch_mock_events_blocking, since=fetch_since
            )
        else:
            from vcenter_event_assistant.collectors.events import (
                fetch_events_from_connection_blocking,
            )

            async with context.open_vcenter_connection() as si:
                rows, max_ts = await _run_blocking(
                    fetch_events_from_connection_blocking, si, since=fetch_since
                )
        events = tuple(
            EventInput(
                occurred_at=row["occurred_at"],
                event_type=row["event_type"],
                message=row["message"],
                vmware_key=int(row["vmware_key"]),
                severity=row.get("severity"),
                user_name=row.get("user_name"),
                entity_name=row.get("entity_name"),
                entity_type=row.get("entity_type"),
                chain_id=row.get("chain_id"),
            )
            for row in rows
        )
        next_cursor = (
            max_ts.isoformat()
            if max_ts is not None
            else (context.previous_cursor or datetime.now(timezone.utc).isoformat())
        )
        return CollectionBatch(events=events, next_cursor=next_cursor)


QUICKSTATS = (
    MetricDefinition(
        "host.cpu.usage_pct", "Host CPU usage", "%", "HostSystem", category="cpu"
    ),
    MetricDefinition(
        "host.mem.usage_pct", "Host memory usage", "%", "HostSystem", category="memory"
    ),
)
PERFORMANCE = tuple(
    MetricDefinition(key, label, unit, "HostSystem", category=category)
    for key, label, unit, category in (
        ("host.net.errors_rx_total", "Network receive errors", "count", "network"),
        ("host.net.errors_tx_total", "Network transmit errors", "count", "network"),
        ("host.net.dropped_rx_total", "Network receive drops", "count", "network"),
        ("host.net.dropped_tx_total", "Network transmit drops", "count", "network"),
        ("host.net.bytes_rx_kbps", "Network receive throughput", "kbps", "network"),
        ("host.net.bytes_tx_kbps", "Network transmit throughput", "kbps", "network"),
        ("host.net.usage_kbps", "Network usage", "kbps", "network"),
        ("host.disk.usage_pct", "Disk usage", "%", "disk"),
        ("host.disk.read_kbps", "Disk read throughput", "kbps", "disk"),
        ("host.disk.write_kbps", "Disk write throughput", "kbps", "disk"),
    )
)
DATASTORE = (
    MetricDefinition(
        "datastore.space.used_pct",
        "Datastore used space",
        "%",
        "Datastore",
        category="storage",
    ),
    MetricDefinition(
        "datastore.space.used_bytes",
        "Datastore used bytes",
        "bytes",
        "Datastore",
        category="storage",
    ),
)


class _MetricCollector(_BaseCollector):
    blocking_function: Callable[[Any], list[dict[str, Any]]]
    mock_keys: frozenset[str]

    async def collect(self, context: CollectionContext) -> CollectionBatch:
        if context.mock_mode:
            from vcenter_event_assistant.mocks.mock_collectors import (
                sample_mock_hosts_blocking,
            )

            rows = await _run_blocking(sample_mock_hosts_blocking)
            rows = [row for row in rows if row["metric_key"] in self.mock_keys]
        else:
            async with context.open_vcenter_connection() as si:
                rows = await _run_blocking(self.blocking_function, si)
        return CollectionBatch(metrics=tuple(_metric(row) for row in rows))


class HostQuickStatsCollector(_MetricCollector):
    from vcenter_event_assistant.collectors.perf import (
        sample_host_quickstats_from_connection_blocking,
    )

    blocking_function = staticmethod(sample_host_quickstats_from_connection_blocking)

    manifest = CollectorManifest(
        "builtin.vcenter.host_quickstats",
        "Host quickStats",
        "1.0.0",
        data_kinds=frozenset({"metric"}),
        metric_definitions=QUICKSTATS,
    )
    mock_keys = frozenset(d.key for d in QUICKSTATS)


class HostPerformanceCollector(_MetricCollector):
    from vcenter_event_assistant.collectors.perf import (
        sample_host_performance_from_connection_blocking,
    )

    blocking_function = staticmethod(sample_host_performance_from_connection_blocking)

    manifest = CollectorManifest(
        "builtin.vcenter.host_performance",
        "Host PerformanceManager",
        "1.0.0",
        data_kinds=frozenset({"metric"}),
        metric_definitions=PERFORMANCE,
    )
    mock_keys = frozenset(d.key for d in PERFORMANCE)


class DatastoreCapacityCollector(_MetricCollector):
    from vcenter_event_assistant.collectors.datastore_metrics import (
        sample_datastore_metrics_blocking,
    )

    blocking_function = staticmethod(sample_datastore_metrics_blocking)

    manifest = CollectorManifest(
        "builtin.vcenter.datastore_capacity",
        "Datastore capacity",
        "1.0.0",
        data_kinds=frozenset({"metric"}),
        metric_definitions=DATASTORE,
    )
    mock_keys = frozenset(d.key for d in DATASTORE)


def builtin_collectors() -> tuple[_BaseCollector, ...]:
    return (
        EventsCollector(),
        HostQuickStatsCollector(),
        HostPerformanceCollector(),
        DatastoreCapacityCollector(),
    )
