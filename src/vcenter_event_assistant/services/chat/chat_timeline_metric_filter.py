"""インシデントタイムライン向けメトリクス項目の閾値・表示整形。"""

from __future__ import annotations

from vcenter_event_assistant.services.chat.chat_incident_timeline import IncidentTimelineEntry
from vcenter_event_assistant.services.chat.chat_period_metrics import (
    METRIC_CPU,
    METRIC_MEM,
    PeriodMetricHostSeries,
)
from vcenter_event_assistant.services.vcenter_labels import first_hostname_label_if_fqdn

# 項目にするのは単位が % の CPU とメモリだけ。ディスクとネットワークの指標（chat_period_metrics の
# DISK_KEYS / NET_KEYS）は値が KB/s で、% の閾値で判定できない。閾値なしで通すと I/O のあるバケットが
# すべて項目になるので、系列ごと外す（Issue #316）。バケット平均は period_metrics として LLM に渡る。
_TIMELINE_METRIC_KEYS: frozenset[str] = frozenset({METRIC_CPU, METRIC_MEM})


def _metric_threshold_for_key(
    metric_key: str,
    *,
    cpu_pct: float | None,
    memory_pct: float | None,
) -> float | None:
    if metric_key == METRIC_CPU:
        return cpu_pct
    if metric_key == METRIC_MEM:
        return memory_pct
    return None


def _host_short_label(entity_name: str) -> str:
    short = first_hostname_label_if_fqdn(entity_name)
    if short:
        return short
    trimmed = (entity_name or "").strip()
    if trimmed:
        return trimmed
    return "-"


def build_timeline_metric_entries(
    series_list: list[PeriodMetricHostSeries],
    *,
    threshold_cpu_pct: float | None,
    threshold_memory_pct: float | None,
) -> list[IncidentTimelineEntry]:
    """CPU とメモリの系列から、0% 除外と閾値適用後のタイムライン項目を返す。それ以外の指標は項目にしない。"""
    out: list[IncidentTimelineEntry] = []
    for series in series_list:
        if series.metric_key not in _TIMELINE_METRIC_KEYS:
            continue
        host_short = _host_short_label(series.entity_name)
        threshold = _metric_threshold_for_key(
            series.metric_key,
            cpu_pct=threshold_cpu_pct,
            memory_pct=threshold_memory_pct,
        )
        for point in series.series:
            if point.avg <= 0:
                continue
            if threshold is not None and point.avg < threshold:
                continue
            out.append(
                IncidentTimelineEntry.for_host_metric(
                    timestamp_utc=point.bucket_start_utc,
                    host=series.entity_name,
                    host_label=host_short,
                    suffix=f" {series.metric_key}: avg={point.avg:.2f}",
                )
            )
    return out
