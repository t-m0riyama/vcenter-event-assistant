"""Built-in collectors exposed through the same contract as external plugins."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from vcenter_event_assistant_plugin_api import (
    CollectionContext,
    CollectorManifest,
    EventInput,
    MetricDefinition,
    MetricSampleInput,
)
from vcenter_event_assistant_plugin_api.collector import (
    CollectorBase,
    EventCollector,
    MetricCollector,
)


def _metric(row: dict[str, Any]) -> MetricSampleInput:
    return MetricSampleInput(
        sampled_at=row["sampled_at"],
        entity_type=row["entity_type"],
        entity_moid=row["entity_moid"],
        entity_name=row["entity_name"],
        metric_key=row["metric_key"],
        value=float(row["value"]),
    )


def _event(row: dict[str, Any]) -> EventInput:
    return EventInput(
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


class EventsCollector(EventCollector):
    """vCenter のイベント。

    カーソルの decode / 1 秒のオーバーラップ / 空バッチでの前進は基底が行う。
    ``max_ts`` は基底が返却イベントの ``occurred_at`` の最大から求めるが、
    ``fetch_events_from_connection_blocking`` が返していた ``max_ts`` も正規化済み行の
    最大なので、同じ値になる。
    """

    manifest = CollectorManifest(
        id="builtin.vcenter.events",
        display_name="vCenter Events",
        version="1.0.0",
        data_kinds=frozenset({"event"}),
        default_interval_seconds=120,
        description=(
            "vCenter のイベント（タスク・アラーム・ログインなど）を、前回取り込んだ"
            "続きから取得します。イベントタブ・要注目スコア・アラート・ダイジェスト・"
            "チャットのすべてがこのデータを使うため、無効にするとイベント側の情報が"
            "更新されなくなります。"
        ),
    )

    def fetch(
        self, si: Any, context: CollectionContext, *, since: datetime | None
    ) -> tuple[EventInput, ...]:
        from vcenter_event_assistant.collectors.events import (
            fetch_events_from_connection_blocking,
        )

        rows, _ = fetch_events_from_connection_blocking(si, since=since)
        return tuple(_event(row) for row in rows)

    def fetch_mock(
        self, context: CollectionContext, *, since: datetime | None
    ) -> tuple[EventInput, ...]:
        from vcenter_event_assistant.mocks.mock_collectors import (
            fetch_mock_events_blocking,
        )

        rows, _ = fetch_mock_events_blocking(since=since)
        return tuple(_event(row) for row in rows)


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


class _MetricCollector(MetricCollector):
    """組み込みのメトリクスコレクタに共通の形。

    接続の開閉・スレッドへの退避・``mock_mode`` の分岐は基底が持つ。ここで足すのは
    「行の辞書を返す既存のブロッキング関数を呼ぶ」ことだけである。
    """

    abstract = True

    blocking_function: Callable[[Any], list[dict[str, Any]]]
    mock_keys: frozenset[str]

    def sample(
        self, si: Any, context: CollectionContext
    ) -> tuple[MetricSampleInput, ...]:
        return tuple(_metric(row) for row in self.blocking_function(si))

    def sample_mock(self, context: CollectionContext) -> tuple[MetricSampleInput, ...]:
        from vcenter_event_assistant.mocks.mock_collectors import (
            sample_mock_hosts_blocking,
        )

        return tuple(
            _metric(row)
            for row in sample_mock_hosts_blocking()
            if row["metric_key"] in self.mock_keys
        )


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
        description=(
            "ESXi ホストの CPU 利用率とメモリ利用率を vCenter の quickStats から"
            "取得します。負荷の軽い呼び出しで、グラフタブと概要ダッシュボードの"
            "基本指標になります。"
        ),
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
        description=(
            "ESXi ホストのネットワーク（送受信エラー・破棄・スループット）とディスク"
            "（使用率・読み書きスループット）の統計を PerformanceManager から取得します。"
            "quickStats より項目が多く、ネットワークやストレージの不調を追うときに使います。"
        ),
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
        description=(
            "データストアの使用容量を、使用率（%）と使用バイト数の 2 つで取得します。"
            "空き容量の逼迫を監視するアラートやグラフの元データになります。"
        ),
    )
    mock_keys = frozenset(d.key for d in DATASTORE)


def builtin_collectors() -> tuple[CollectorBase, ...]:
    return (
        EventsCollector(),
        HostQuickStatsCollector(),
        HostPerformanceCollector(),
        DatastoreCapacityCollector(),
    )
