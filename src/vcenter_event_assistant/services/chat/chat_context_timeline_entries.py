"""チャット incident timeline エントリの純粋関数（DB 非依存）。"""

from __future__ import annotations

from datetime import datetime, timedelta

from vcenter_event_assistant.services.chat.chat_event_time_buckets import EventTimeBucketsPayload
from vcenter_event_assistant.services.chat.chat_incident_timeline import IncidentTimelineEntry
from vcenter_event_assistant.services.chat.chat_period_metrics import PeriodMetricsPayload
from vcenter_event_assistant.services.chat.chat_timeline_metric_filter import build_timeline_metric_entries
from vcenter_event_assistant.services.digest.digest_context import DigestContext


def build_auto_trigger_alert_entries(
    *,
    period_metrics: PeriodMetricsPayload | None,
    event_time_buckets: EventTimeBucketsPayload | None,
) -> list[IncidentTimelineEntry]:
    """自動トリガー由来の alert エントリを生成する。"""

    entries: list[IncidentTimelineEntry] = []
    if event_time_buckets is None or not event_time_buckets.buckets:
        return entries

    busiest_bucket = max(
        event_time_buckets.buckets,
        key=lambda row: int(getattr(row, "total", 0) or 0),
        default=None,
    )
    critical_burst_timestamp: datetime | None = None
    has_critical_burst = bool(
        busiest_bucket is not None and int(getattr(busiest_bucket, "total", 0) or 0) >= 10
    )
    if has_critical_burst and busiest_bucket is not None:
        critical_burst_timestamp = busiest_bucket.bucket_start_utc
    has_sustained_breach = False
    sustained_breach_timestamp: datetime | None = None

    if period_metrics is not None and period_metrics.cpu:
        bucket_interval = timedelta(minutes=period_metrics.bucket_minutes)
        for host in period_metrics.cpu:
            points = sorted(
                (point for point in host.series if point.avg is not None),
                key=lambda point: point.bucket_start_utc,
            )
            consecutive = 0
            previous_timestamp: datetime | None = None
            for point in points:
                current_timestamp = point.bucket_start_utc
                if (
                    previous_timestamp is None
                    or current_timestamp - previous_timestamp != bucket_interval
                ):
                    consecutive = 0
                previous_timestamp = current_timestamp

                if float(point.avg) >= 90:
                    consecutive += 1
                    if consecutive >= 3:
                        has_sustained_breach = True
                        candidate_timestamp = current_timestamp
                        if (
                            sustained_breach_timestamp is None
                            or candidate_timestamp < sustained_breach_timestamp
                        ):
                            sustained_breach_timestamp = candidate_timestamp
                        break
                else:
                    consecutive = 0

    default_trigger_timestamp = event_time_buckets.buckets[0].bucket_start_utc
    critical_timestamp = critical_burst_timestamp or default_trigger_timestamp
    sustained_timestamp = sustained_breach_timestamp or default_trigger_timestamp

    if has_critical_burst:
        entries.append(
            IncidentTimelineEntry(
                timestamp_utc=critical_timestamp,
                kind="alert",
                title="自動トリガー: Critical burst",
                trigger_id="critical_burst",
            )
        )
    if has_sustained_breach:
        entries.append(
            IncidentTimelineEntry(
                timestamp_utc=sustained_timestamp,
                kind="alert",
                title="自動トリガー: Sustained breach",
                trigger_id="sustained_breach",
            )
        )
    if has_critical_burst and has_sustained_breach:
        entries.append(
            IncidentTimelineEntry(
                timestamp_utc=max(critical_timestamp, sustained_timestamp),
                kind="alert",
                title="自動トリガー: Multi-signal overlap",
                trigger_id="multi_signal_overlap",
            )
        )
    return entries


def build_chat_incident_timeline_entries(
    *,
    context: DigestContext,
    timeline_event_time_buckets: EventTimeBucketsPayload | None,
    timeline_period_metrics: PeriodMetricsPayload | None,
    include_period_metrics_cpu: bool,
    include_period_metrics_memory: bool,
    include_period_metrics_disk_io: bool,
    include_period_metrics_network_io: bool,
    metric_threshold_cpu_pct: float | None,
    metric_threshold_memory_pct: float | None,
    metric_threshold_disk_pct: float | None,
    metric_threshold_network_pct: float | None,
) -> list[IncidentTimelineEntry]:
    """digest / バケット / メトリクスから incident timeline エントリ列を組み立てる。"""

    timeline_entries: list[IncidentTimelineEntry] = []
    if timeline_event_time_buckets is not None:
        for row in timeline_event_time_buckets.buckets:
            for alert in getattr(row, "alert_top_types", []):
                timeline_entries.append(
                    IncidentTimelineEntry(
                        timestamp_utc=row.bucket_start_utc,
                        kind="alert",
                        title=f"{alert.event_type} ({alert.count}件, max score={alert.max_notable_score})",
                    )
                )
            alert_other_count = int(getattr(row, "alert_other_count", 0) or 0)
            if alert_other_count > 0:
                timeline_entries.append(
                    IncidentTimelineEntry(
                        timestamp_utc=row.bucket_start_utc,
                        kind="alert",
                        title=f"その他アラート ({alert_other_count}件)",
                    )
                )
        timeline_entries.extend(
            build_auto_trigger_alert_entries(
                period_metrics=timeline_period_metrics,
                event_time_buckets=timeline_event_time_buckets,
            )
        )
    else:
        for g in context.top_notable_event_groups:
            timeline_entries.append(
                IncidentTimelineEntry(
                    timestamp_utc=g.occurred_at_last,
                    kind="alert",
                    title=f"{g.event_type} ({g.occurrence_count}件)",
                )
            )
    if timeline_event_time_buckets is not None:
        for row in timeline_event_time_buckets.buckets:
            timeline_entries.append(
                IncidentTimelineEntry(
                    timestamp_utc=row.bucket_start_utc,
                    kind="event",
                    title=f"イベント件数: {row.total}",
                )
            )
    else:
        for g in context.top_notable_event_groups:
            timeline_entries.append(
                IncidentTimelineEntry(
                    timestamp_utc=g.occurred_at_last,
                    kind="event",
                    title=f"関連イベント: {g.occurrence_count}件",
                )
            )
    if timeline_period_metrics is not None:
        selected_metric_series = [
            *((timeline_period_metrics.cpu or []) if include_period_metrics_cpu else []),
            *((timeline_period_metrics.memory or []) if include_period_metrics_memory else []),
            *((timeline_period_metrics.disk or []) if include_period_metrics_disk_io else []),
            *((timeline_period_metrics.network or []) if include_period_metrics_network_io else []),
        ]
        timeline_entries.extend(
            build_timeline_metric_entries(
                selected_metric_series,
                threshold_cpu_pct=metric_threshold_cpu_pct,
                threshold_memory_pct=metric_threshold_memory_pct,
                threshold_disk_pct=metric_threshold_disk_pct,
                threshold_network_pct=metric_threshold_network_pct,
            )
        )
    else:
        for row in context.high_cpu_hosts:
            timeline_entries.append(
                IncidentTimelineEntry(
                    timestamp_utc=row.sampled_at,
                    kind="metric",
                    title=f"host.cpu.usage_pct: {row.entity_name}={row.value:.2f}",
                )
            )
        for row in context.high_mem_hosts:
            timeline_entries.append(
                IncidentTimelineEntry(
                    timestamp_utc=row.sampled_at,
                    kind="metric",
                    title=f"host.mem.usage_pct: {row.entity_name}={row.value:.2f}",
                )
            )
    return timeline_entries
