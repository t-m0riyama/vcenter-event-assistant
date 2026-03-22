"""Host PerformanceManager samples for net/disk counters (blocking, pyVmomi)."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any

from pyVmomi import vim

logger = logging.getLogger(__name__)

_DEFAULT_REALTIME_INTERVAL_SEC = 20

# `MetricSample.entity_moid` の上限（複合 ID 用にホスト MOID + サフィックスを収める）
_MAX_ENTITY_MOID_LEN = 256
_MAX_ENTITY_NAME_LEN = 1024


def _sanitize_perf_instance_for_moid(instance: str, *, host_moid_len: int) -> str:
    """
    インスタンス名を `entity_moid` のサフィックスとして安全な短い文字列にする。
    長い NAA 等はハッシュで短縮する。
    """
    raw = (instance or "").strip()
    safe = re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_")
    if not safe:
        safe = "instance"
    # "host_moid:" + suffix が _MAX_ENTITY_MOID_LEN 以下
    max_suffix = max(8, _MAX_ENTITY_MOID_LEN - host_moid_len - 1)
    if len(safe) > max_suffix:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        prefix_len = max(0, max_suffix - 1 - len(digest))
        safe = f"{safe[:prefix_len]}_{digest}" if prefix_len else digest
        if len(safe) > max_suffix:
            safe = safe[:max_suffix]
    return safe


def _composite_entity_moid(host_moid: str, instance: str) -> str:
    suffix = _sanitize_perf_instance_for_moid(instance, host_moid_len=len(host_moid))
    out = f"{host_moid}:{suffix}"
    if len(out) <= _MAX_ENTITY_MOID_LEN:
        return out
    return out[:_MAX_ENTITY_MOID_LEN]


def _composite_entity_name(host_name: str, instance: str) -> str:
    s = f"{host_name} / {instance}"
    if len(s) <= _MAX_ENTITY_NAME_LEN:
        return s
    return s[: _MAX_ENTITY_NAME_LEN - 1] + "…"

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


def _round_metric_value(metric_key: str, val: float) -> float:
    if metric_key.endswith("_pct"):
        return round(val, 2)
    if metric_key.endswith("_kbps") or metric_key.endswith("_total"):
        return round(val, 4)
    return float(val)


def _is_aggregate_perf_instance(instance: str) -> bool:
    """
    vSphere の集約に相当する instance かどうか。
    空文字、`*`、英字 Total / All（大小無視）を集約とみなす。
    """
    if instance == "":
        return True
    s = instance.strip()
    if s == "*":
        return True
    if s.casefold() in ("total", "all"):
        return True
    return False


def _drop_aggregate_instances_when_named_exist(by_pair: dict[tuple[int, str], float]) -> None:
    """
    同一 counterId に「名前付き」インスタンスが 1 本以上あるとき、
    集約インスタンスに対応するキーを by_pair から除く（グラフの重複系列を防ぐ）。
    集約のみのときは何もしない。
    """
    by_cid: dict[int, set[str]] = {}
    for cid, inst in by_pair:
        by_cid.setdefault(cid, set()).add(inst)
    to_drop: list[tuple[int, str]] = []
    for cid, insts in by_cid.items():
        non_agg = [i for i in insts if not _is_aggregate_perf_instance(i)]
        if len(insts) >= 2 and len(non_agg) >= 1:
            for i in insts:
                if _is_aggregate_perf_instance(i):
                    to_drop.append((cid, i))
    for key in to_drop:
        by_pair.pop(key, None)


def parse_perf_query_result_rows(
    *,
    entity_moid: str,
    entity_name: str,
    sampled_at: datetime,
    perf_entity_metrics: list[Any],
    counter_id_to_metric_key: dict[int, str],
) -> list[dict[str, Any]]:
    """
    QueryPerf の結果をメトリクス行に変換する。

    同一 counterId の複数インスタンス（NIC / デバイス）は **合算せず**、系列ごとに 1 行とする。
    `instance` が空のときはホスト側の集約カウンタとして `entity_moid` / `entity_name` をそのまま使う。

    同一 counter で名前付きインスタンスと集約（空 / `*` / Total / All）が併存する場合は、
    集約に対応する行を出さない（グラフで Total 等の重複系列を避ける）。
    """
    # (counterId, instance) ごとに最新値（重複系列があれば上書き）
    by_pair: dict[tuple[int, str], float] = {}
    for pem in perf_entity_metrics:
        for ser in getattr(pem, "value", None) or []:
            mid = getattr(ser, "id", None)
            if mid is None:
                continue
            cid = int(getattr(mid, "counterId", 0) or 0)
            if cid not in counter_id_to_metric_key:
                continue
            inst = getattr(mid, "instance", "") or ""
            by_pair[(cid, inst)] = _latest_in_series(ser)

    _drop_aggregate_instances_when_named_exist(by_pair)

    rows: list[dict[str, Any]] = []
    for (cid, inst), raw_val in by_pair.items():
        mk = counter_id_to_metric_key.get(cid)
        if not mk:
            continue
        val = _round_metric_value(mk, float(raw_val))
        if inst == "":
            emoid = entity_moid
            ename = entity_name
        else:
            emoid = _composite_entity_moid(entity_moid, inst)
            ename = _composite_entity_name(entity_name, inst)
        rows.append(
            {
                "sampled_at": sampled_at,
                "entity_type": "HostSystem",
                "entity_moid": emoid,
                "entity_name": ename,
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
