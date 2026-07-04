"""chat_context_timeline_entries の characterization テスト。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from vcenter_event_assistant.api.schemas.dashboard import HighCpuHostRow, HighMemHostRow
from vcenter_event_assistant.services.chat.chat_context_timeline_entries import (
    build_auto_trigger_alert_entries,
    build_chat_incident_timeline_entries,
)
from vcenter_event_assistant.services.chat.chat_event_time_buckets import (
    AlertTypeBucketRow,
    EventTimeBucketRow,
    EventTimeBucketsPayload,
)
from vcenter_event_assistant.services.chat.chat_period_metrics import (
    PeriodMetricBucketPoint,
    PeriodMetricHostSeries,
    PeriodMetricsPayload,
)
from vcenter_event_assistant.services.digest.digest_context import (
    DigestContext,
    DigestNotableEventGroup,
)


def _ts(hour: int = 10) -> datetime:
    return datetime(2026, 5, 7, hour, 0, 0, tzinfo=timezone.utc)


def _minimal_ctx(**kwargs: object) -> DigestContext:
    t0 = _ts(0)
    t1 = _ts(1)
    defaults = {
        "from_utc": t0,
        "to_utc": t1,
        "vcenter_count": 0,
        "total_events": 0,
        "notable_events_count": 0,
        "top_notable_event_groups": [],
        "top_event_types": [],
        "high_cpu_hosts": [],
        "high_mem_hosts": [],
    }
    defaults.update(kwargs)
    return DigestContext(**defaults)  # type: ignore[arg-type]


def test_build_auto_trigger_alert_entries_returns_empty_without_buckets() -> None:
    assert build_auto_trigger_alert_entries(period_metrics=None, event_time_buckets=None) == []


def test_build_auto_trigger_alert_entries_emits_critical_burst_when_total_ge_10() -> None:
    t0 = _ts()
    buckets = EventTimeBucketsPayload(
        bucket_minutes=15,
        from_utc=t0,
        to_utc=t0 + timedelta(hours=1),
        buckets=[
            EventTimeBucketRow(bucket_start_utc=t0, total=10),
            EventTimeBucketRow(bucket_start_utc=t0 + timedelta(minutes=15), total=3),
        ],
    )
    entries = build_auto_trigger_alert_entries(period_metrics=None, event_time_buckets=buckets)
    assert len(entries) == 1
    assert entries[0].trigger_id == "critical_burst"
    assert entries[0].kind == "alert"
    assert entries[0].timestamp_utc == t0


def test_build_auto_trigger_alert_entries_emits_sustained_breach_on_three_consecutive_high_cpu() -> None:
    t0 = _ts()
    interval = timedelta(minutes=15)
    cpu_series = PeriodMetricHostSeries(
        entity_name="esxi-01",
        entity_moid="host-1",
        metric_key="host.cpu.usage_pct",
        series=[
            PeriodMetricBucketPoint(bucket_start_utc=t0, avg=91.0, n=1),
            PeriodMetricBucketPoint(bucket_start_utc=t0 + interval, avg=92.0, n=1),
            PeriodMetricBucketPoint(bucket_start_utc=t0 + 2 * interval, avg=93.0, n=1),
        ],
    )
    period_metrics = PeriodMetricsPayload(
        bucket_minutes=15,
        from_utc=t0,
        to_utc=t0 + timedelta(hours=1),
        cpu=[cpu_series],
    )
    buckets = EventTimeBucketsPayload(
        bucket_minutes=15,
        from_utc=t0,
        to_utc=t0 + timedelta(hours=1),
        buckets=[EventTimeBucketRow(bucket_start_utc=t0, total=2)],
    )
    entries = build_auto_trigger_alert_entries(
        period_metrics=period_metrics,
        event_time_buckets=buckets,
    )
    assert any(e.trigger_id == "sustained_breach" for e in entries)
    sustained = next(e for e in entries if e.trigger_id == "sustained_breach")
    assert sustained.timestamp_utc == t0 + 2 * interval


def test_build_auto_trigger_alert_entries_emits_multi_signal_overlap_when_both_triggers() -> None:
    t0 = _ts()
    interval = timedelta(minutes=15)
    cpu_series = PeriodMetricHostSeries(
        entity_name="esxi-01",
        entity_moid="host-1",
        metric_key="host.cpu.usage_pct",
        series=[
            PeriodMetricBucketPoint(bucket_start_utc=t0, avg=95.0, n=1),
            PeriodMetricBucketPoint(bucket_start_utc=t0 + interval, avg=95.0, n=1),
            PeriodMetricBucketPoint(bucket_start_utc=t0 + 2 * interval, avg=95.0, n=1),
        ],
    )
    period_metrics = PeriodMetricsPayload(
        bucket_minutes=15,
        from_utc=t0,
        to_utc=t0 + timedelta(hours=1),
        cpu=[cpu_series],
    )
    buckets = EventTimeBucketsPayload(
        bucket_minutes=15,
        from_utc=t0,
        to_utc=t0 + timedelta(hours=1),
        buckets=[EventTimeBucketRow(bucket_start_utc=t0, total=12)],
    )
    entries = build_auto_trigger_alert_entries(
        period_metrics=period_metrics,
        event_time_buckets=buckets,
    )
    trigger_ids = {e.trigger_id for e in entries}
    assert trigger_ids == {"critical_burst", "sustained_breach", "multi_signal_overlap"}


def test_build_chat_incident_timeline_entries_from_event_buckets_includes_alert_top_types() -> None:
    t0 = _ts()
    buckets = EventTimeBucketsPayload(
        bucket_minutes=15,
        from_utc=t0,
        to_utc=t0 + timedelta(hours=1),
        buckets=[
            EventTimeBucketRow(
                bucket_start_utc=t0,
                total=5,
                alert_top_types=[
                    AlertTypeBucketRow(event_type="vim.event.Alarm", count=3, max_notable_score=80),
                ],
                alert_other_count=2,
            ),
        ],
    )
    entries = build_chat_incident_timeline_entries(
        context=_minimal_ctx(),
        timeline_event_time_buckets=buckets,
        timeline_period_metrics=None,
        include_period_metrics_cpu=False,
        include_period_metrics_memory=False,
        include_period_metrics_disk_io=False,
        include_period_metrics_network_io=False,
        metric_threshold_cpu_pct=None,
        metric_threshold_memory_pct=None,
        metric_threshold_disk_pct=None,
        metric_threshold_network_pct=None,
    )
    alert_titles = [e.title for e in entries if e.kind == "alert"]
    assert any("vim.event.Alarm" in title for title in alert_titles)
    assert any("その他アラート (2件)" in title for title in alert_titles)
    event_titles = [e.title for e in entries if e.kind == "event"]
    assert event_titles == ["イベント件数: 5"]


def test_build_chat_incident_timeline_entries_without_buckets_uses_notable_groups() -> None:
    t0 = _ts()
    ctx = _minimal_ctx(
        top_notable_event_groups=[
            DigestNotableEventGroup(
                event_type="vim.event.VmPoweredOn",
                occurrence_count=4,
                notable_score=60,
                occurred_at_first=t0,
                occurred_at_last=t0,
                entity_name="vm-01",
                message="powered on",
            ),
        ],
    )
    entries = build_chat_incident_timeline_entries(
        context=ctx,
        timeline_event_time_buckets=None,
        timeline_period_metrics=None,
        include_period_metrics_cpu=False,
        include_period_metrics_memory=False,
        include_period_metrics_disk_io=False,
        include_period_metrics_network_io=False,
        metric_threshold_cpu_pct=None,
        metric_threshold_memory_pct=None,
        metric_threshold_disk_pct=None,
        metric_threshold_network_pct=None,
    )
    assert [e.kind for e in entries] == ["alert", "event"]
    assert "vim.event.VmPoweredOn (4件)" in entries[0].title
    assert entries[1].title == "関連イベント: 4件"


def test_build_chat_incident_timeline_entries_without_period_metrics_uses_high_cpu_mem_from_context() -> None:
    t0 = _ts()
    vc_id = str(uuid.uuid4())
    ctx = _minimal_ctx(
        high_cpu_hosts=[
            HighCpuHostRow(
                vcenter_id=vc_id,
                vcenter_label="vc-01",
                entity_name="esxi-01.example.local",
                entity_moid="host-1",
                value=88.5,
                sampled_at=t0,
            ),
        ],
        high_mem_hosts=[
            HighMemHostRow(
                vcenter_id=vc_id,
                vcenter_label="vc-01",
                entity_name="esxi-02.example.local",
                entity_moid="host-2",
                value=77.2,
                sampled_at=t0,
            ),
        ],
    )
    entries = build_chat_incident_timeline_entries(
        context=ctx,
        timeline_event_time_buckets=None,
        timeline_period_metrics=None,
        include_period_metrics_cpu=False,
        include_period_metrics_memory=False,
        include_period_metrics_disk_io=False,
        include_period_metrics_network_io=False,
        metric_threshold_cpu_pct=None,
        metric_threshold_memory_pct=None,
        metric_threshold_disk_pct=None,
        metric_threshold_network_pct=None,
    )
    metric_titles = [e.title for e in entries if e.kind == "metric"]
    assert metric_titles == [
        "host.cpu.usage_pct: esxi-01.example.local=88.50",
        "host.mem.usage_pct: esxi-02.example.local=77.20",
    ]
