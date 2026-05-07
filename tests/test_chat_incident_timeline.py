"""chat_incident_timeline の整形ルールテスト。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from vcenter_event_assistant.services.chat_incident_timeline import (
    IncidentTimelineEntry,
    build_chat_incident_timeline,
)


def _ts() -> datetime:
    return datetime(2026, 5, 7, 10, 0, 0, tzinfo=timezone.utc)


def test_build_chat_incident_timeline_orders_items_within_same_timestamp() -> None:
    """同一時刻内は Alert > Event > Metric で並ぶ。"""
    at = _ts()
    out = build_chat_incident_timeline(
        [
            IncidentTimelineEntry(timestamp_utc=at, kind="metric", title="m1"),
            IncidentTimelineEntry(timestamp_utc=at, kind="event", title="e1"),
            IncidentTimelineEntry(timestamp_utc=at, kind="alert", title="a1"),
            IncidentTimelineEntry(timestamp_utc=at, kind="event", title="e2"),
        ],
    )

    assert len(out.columns) == 1
    assert [i.kind for i in out.columns[0].visible_items] == [
        "alert",
        "event",
        "event",
        "metric",
    ]


def test_build_chat_incident_timeline_limits_visible_items_to_top_10() -> None:
    """同一時刻の表示は上位10件で、それ以外は hidden_count に入る。"""
    at = _ts()
    entries = [
        IncidentTimelineEntry(timestamp_utc=at, kind="alert", title=f"a{i}")
        for i in range(4)
    ] + [
        IncidentTimelineEntry(timestamp_utc=at, kind="event", title=f"e{i}")
        for i in range(4)
    ] + [
        IncidentTimelineEntry(timestamp_utc=at, kind="metric", title=f"m{i}")
        for i in range(5)
    ]

    out = build_chat_incident_timeline(entries)
    col = out.columns[0]
    assert len(col.visible_items) == 10
    assert col.hidden_count == 3
    assert [i.kind for i in col.visible_items] == [
        "alert",
        "alert",
        "alert",
        "alert",
        "event",
        "event",
        "event",
        "event",
        "metric",
        "metric",
    ]


def test_build_chat_incident_timeline_groups_by_timestamp() -> None:
    """時刻ごとに列化し、時刻は新しい順で並ぶ。"""
    newer = datetime(2026, 5, 7, 10, 1, 0, tzinfo=timezone.utc)
    older = datetime(2026, 5, 7, 10, 0, 0, tzinfo=timezone.utc)

    out = build_chat_incident_timeline(
        [
            IncidentTimelineEntry(timestamp_utc=older, kind="event", title="older"),
            IncidentTimelineEntry(timestamp_utc=newer, kind="alert", title="newer"),
        ],
    )

    assert [c.timestamp_utc for c in out.columns] == [newer, older]


def test_build_chat_incident_timeline_rejects_invalid_visible_items_limit() -> None:
    """max_visible_items_per_timestamp が 1 未満なら ValueError。"""
    at = _ts()
    entries = [IncidentTimelineEntry(timestamp_utc=at, kind="event", title="e1")]

    with pytest.raises(ValueError):
        build_chat_incident_timeline(entries, max_visible_items_per_timestamp=0)


def test_build_chat_incident_timeline_rejects_invalid_bucket_seconds() -> None:
    """bucket_seconds が 1 未満なら ValueError。"""
    at = _ts()
    entries = [IncidentTimelineEntry(timestamp_utc=at, kind="event", title="e1")]

    with pytest.raises(ValueError):
        build_chat_incident_timeline(entries, bucket_seconds=0)


def test_build_chat_incident_timeline_sets_bucket_range_when_bucket_seconds_given() -> None:
    """bucket_seconds があると各列に開始/終了時刻を付与する。"""
    at = _ts()
    out = build_chat_incident_timeline(
        [IncidentTimelineEntry(timestamp_utc=at, kind="event", title="e1")],
        bucket_seconds=300,
    )

    assert len(out.columns) == 1
    col = out.columns[0]
    assert col.bucket_start_utc == at
    assert col.bucket_end_utc == at + timedelta(seconds=300)


def test_build_chat_incident_timeline_groups_same_instant_across_timezones() -> None:
    """aware timezone と UTC の同一瞬間は同一列に入る。"""
    utc_ts = datetime(2026, 5, 7, 10, 0, 0, tzinfo=timezone.utc)
    jst_ts_same_instant = datetime(
        2026,
        5,
        7,
        19,
        0,
        0,
        tzinfo=timezone(timedelta(hours=9)),
    )
    out = build_chat_incident_timeline(
        [
            IncidentTimelineEntry(timestamp_utc=utc_ts, kind="event", title="utc"),
            IncidentTimelineEntry(
                timestamp_utc=jst_ts_same_instant,
                kind="alert",
                title="aware",
            ),
        ],
    )

    assert len(out.columns) == 1
    assert out.columns[0].timestamp_utc == utc_ts
    assert [i.title for i in out.columns[0].visible_items] == ["aware", "utc"]
    assert all(i.timestamp_utc.tzinfo == timezone.utc for i in out.columns[0].items)
    assert all(i.timestamp_utc == utc_ts for i in out.columns[0].items)


def test_build_chat_incident_timeline_treats_naive_datetime_as_utc() -> None:
    """naive datetime は UTC として扱われる。"""
    aware_utc = datetime(2026, 5, 7, 10, 0, 0, tzinfo=timezone.utc)
    naive_same_wall_time = datetime(2026, 5, 7, 10, 0, 0)
    out = build_chat_incident_timeline(
        [
            IncidentTimelineEntry(timestamp_utc=aware_utc, kind="alert", title="aware"),
            IncidentTimelineEntry(timestamp_utc=naive_same_wall_time, kind="event", title="naive"),
        ],
    )

    assert len(out.columns) == 1
    assert out.columns[0].timestamp_utc == aware_utc
    assert [i.kind for i in out.columns[0].visible_items] == ["alert", "event"]


def test_build_chat_incident_timeline_preserves_input_order_within_same_kind() -> None:
    """同一 kind 内の入力順は保持される。"""
    at = _ts()
    out = build_chat_incident_timeline(
        [
            IncidentTimelineEntry(timestamp_utc=at, kind="event", title="event-2"),
            IncidentTimelineEntry(timestamp_utc=at, kind="event", title="event-1"),
            IncidentTimelineEntry(timestamp_utc=at, kind="alert", title="alert-1"),
            IncidentTimelineEntry(timestamp_utc=at, kind="event", title="event-3"),
        ],
    )

    assert [i.title for i in out.columns[0].visible_items] == [
        "alert-1",
        "event-2",
        "event-1",
        "event-3",
    ]
