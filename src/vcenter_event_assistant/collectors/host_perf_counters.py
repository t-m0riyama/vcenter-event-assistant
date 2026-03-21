"""Host PerformanceManager samples for net/disk counters (blocking, pyVmomi)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pyVmomi import vim

logger = logging.getLogger(__name__)

_DEFAULT_REALTIME_INTERVAL_SEC = 20

# (metric_key, perf group, counter name, rollup)
_TARGET_SPECS: tuple[tuple[str, str, str, int], ...] = (
    ("host.net.errors_rx_total", "net", "errorsRx", vim.PerformanceManager.CounterInfo.RollupType.summation),
    ("host.net.errors_tx_total", "net", "errorsTx", vim.PerformanceManager.CounterInfo.RollupType.summation),
    ("host.net.dropped_rx_total", "net", "droppedRx", vim.PerformanceManager.CounterInfo.RollupType.summation),
    ("host.net.dropped_tx_total", "net", "droppedTx", vim.PerformanceManager.CounterInfo.RollupType.summation),
    ("host.net.bytes_rx_kbps", "net", "bytesRx", vim.PerformanceManager.CounterInfo.RollupType.average),
    ("host.net.bytes_tx_kbps", "net", "bytesTx", vim.PerformanceManager.CounterInfo.RollupType.average),
    ("host.net.usage_kbps", "net", "usage", vim.PerformanceManager.CounterInfo.RollupType.average),
    ("host.disk.usage_pct", "disk", "usage", vim.PerformanceManager.CounterInfo.RollupType.average),
    ("host.disk.read_kbps", "disk", "read", vim.PerformanceManager.CounterInfo.RollupType.average),
    ("host.disk.write_kbps", "disk", "write", vim.PerformanceManager.CounterInfo.RollupType.average),
)


def _counter_key_by_group_name_rollup(
    perf_manager: vim.PerformanceManager,
    group: str,
    name: str,
    rollup: int,
) -> int | None:
    """Resolve vSphere performance counter key (integer id)."""
    for c in perf_manager.perfCounter:
        if c.groupInfo.key == group and c.nameInfo.key == name and c.rollupType == rollup:
            return int(c.key)
    return None


def _build_metric_key_by_counter_id(perf_manager: vim.PerformanceManager) -> dict[int, str]:
    out: dict[int, str] = {}
    for metric_key, group, name, rollup in _TARGET_SPECS:
        cid = _counter_key_by_group_name_rollup(perf_manager, group, name, rollup)
        if cid is not None:
            out[cid] = metric_key
    return out


def _realtime_interval_id(perf_manager: vim.PerformanceManager, host: Any) -> int:
    try:
        summary = perf_manager.QueryPerfProviderSummary(host)
        if summary is not None and summary.refreshRate and summary.refreshRate > 0:
            return int(summary.refreshRate)
    except Exception:
        logger.warning("QueryPerfProviderSummary failed; using default realtime interval", exc_info=True)
    return _DEFAULT_REALTIME_INTERVAL_SEC


def _latest_in_series(series: vim.PerfMetricSeries) -> float:
    vals = getattr(series, "value", None) or []
    if not vals:
        return 0.0
    return float(vals[-1])


def parse_perf_query_result_rows(
    *,
    entity_moid: str,
    entity_name: str,
    sampled_at: datetime,
    perf_entity_metrics: list[Any],
    counter_id_to_metric_key: dict[int, str],
) -> list[dict[str, Any]]:
    """
    Turn QueryPerf results into metric sample dicts.

    Sums values across instances (NICs / devices) that share the same counter id.
    """
    totals: dict[int, float] = {}
    for pem in perf_entity_metrics:
        for ser in getattr(pem, "value", None) or []:
            mid = getattr(ser, "id", None)
            if mid is None:
                continue
            cid = int(getattr(mid, "counterId", 0) or 0)
            if cid not in counter_id_to_metric_key:
                continue
            v = _latest_in_series(ser)
            totals[cid] = totals.get(cid, 0.0) + v

    rows: list[dict[str, Any]] = []
    for cid, total in totals.items():
        mk = counter_id_to_metric_key.get(cid)
        if not mk:
            continue
        val = total
        if mk.endswith("_pct"):
            val = round(val, 2)
        elif mk.endswith("_kbps") or mk.endswith("_total"):
            val = round(val, 4)
        rows.append(
            {
                "sampled_at": sampled_at,
                "entity_type": "HostSystem",
                "entity_moid": entity_moid,
                "entity_name": entity_name,
                "metric_key": mk,
                "value": float(val),
            }
        )
    return rows


def collect_host_perf_metric_rows(si: Any, host: Any) -> list[dict[str, Any]]:
    """
    Query realtime PerformanceManager stats for one host and return sample rows.

    On failure, logs a warning and returns an empty list (caller keeps CPU/mem samples).
    """
    now = datetime.now(timezone.utc)
    moid = host._moId
    name = host.name
    try:
        content = si.RetrieveContent()
        perf_manager = content.perfManager
        counter_id_to_metric_key = _build_metric_key_by_counter_id(perf_manager)
        if not counter_id_to_metric_key:
            logger.warning("no host perf counter mappings resolved for host=%s", name)
            return []

        interval_id = _realtime_interval_id(perf_manager, host)
        available = perf_manager.QueryAvailablePerfMetric(host, intervalId=interval_id)
        wanted_ids = set(counter_id_to_metric_key.keys())
        metric_ids: list[vim.PerfMetricId] = []
        seen: set[tuple[int, str]] = set()
        for av in available or []:
            aid = getattr(av, "counterId", None)
            if aid is None:
                continue
            cid = int(aid)
            if cid not in wanted_ids:
                continue
            inst = getattr(av, "instance", "") or ""
            key = (cid, inst)
            if key in seen:
                continue
            seen.add(key)
            metric_ids.append(vim.PerfMetricId(counterId=cid, instance=inst))

        if not metric_ids:
            logger.warning("no matching perf metric instances for host=%s", name)
            return []

        spec = vim.PerfQuerySpec()
        spec.entity = host
        spec.intervalId = interval_id
        spec.maxSample = 1
        spec.metricId = metric_ids

        result = perf_manager.QueryPerf(querySpec=[spec])
        return parse_perf_query_result_rows(
            entity_moid=moid,
            entity_name=name,
            sampled_at=now,
            perf_entity_metrics=list(result or []),
            counter_id_to_metric_key=counter_id_to_metric_key,
        )
    except Exception:
        logger.warning("host perf metrics failed host=%s", name, exc_info=True)
        return []
