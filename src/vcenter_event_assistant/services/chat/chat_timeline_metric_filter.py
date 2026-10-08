"""インシデントタイムライン向けメトリクス項目の閾値・表示整形。"""

from __future__ import annotations

from vcenter_event_assistant.services.chat.chat_incident_timeline import IncidentTimelineEntry
from vcenter_event_assistant.services.chat.chat_period_metrics import (
    DISK_KEYS,
    METRIC_CPU,
    METRIC_MEM,
    NET_KEYS,
    PeriodMetricHostSeries,
)
from vcenter_event_assistant.services.vcenter_labels import first_hostname_label_if_fqdn


def _metric_threshold_for_key(
    metric_key: str,
    *,
    cpu_pct: float | None,
    memory_pct: float | None,
    disk_pct: float | None,
    network_pct: float | None,
) -> float | None:
    if metric_key == METRIC_CPU:
        return cpu_pct
    if metric_key == METRIC_MEM:
        return memory_pct
    if metric_key in DISK_KEYS:
        return disk_pct
    if metric_key in NET_KEYS:
        return network_pct
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
    threshold_disk_pct: float | None,
    threshold_network_pct: float | None,
) -> list[IncidentTimelineEntry]:
    """0% 除外とカテゴリ閾値適用後にタイムライン項目を返す。"""
    out: list[IncidentTimelineEntry] = []
    for series in series_list:
        host_short = _host_short_label(series.entity_name)
        threshold = _metric_threshold_for_key(
            series.metric_key,
            cpu_pct=threshold_cpu_pct,
            memory_pct=threshold_memory_pct,
            disk_pct=threshold_disk_pct,
            network_pct=threshold_network_pct,
        )
        for point in series.series:
            if point.avg <= 0:
                continue
            if threshold is not None and point.avg < threshold:
                continue
            out.append(
                IncidentTimelineEntry(
                    timestamp_utc=point.bucket_start_utc,
                    kind="metric",
                    title=f"{host_short} {series.metric_key}: avg={point.avg:.2f}",
                )
            )
    return out
