"""タイムライン表示 API のサービスの純粋関数（DB を使わない）のテスト。"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from vcenter_event_assistant.services.incident_timeline_view import (
    EventTypeStats,
    TimelineEntry,
    alert_level,
    alert_title,
    bucket_index,
    build_overview,
    choose_bucket_seconds,
    count_per_bucket,
    entity_matches,
    event_level,
    first_signal,
    merge_consecutive,
    overview_bucket_count,
    pick_new_event_types,
    select_within_limit,
    sort_entries,
    summarize_event_types,
    top_entities,
)

T0 = datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
V1 = uuid.UUID("00000000-0000-0000-0000-000000000001")
V2 = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _at(minute: float) -> datetime:
    return T0 + timedelta(minutes=minute)


def _ev(
    source_id: int,
    minute: float,
    event_type: str = "A",
    entity: str | None = "h1",
    *,
    score: int = 30,
    level: str = "info",
    vcenter_id: uuid.UUID | None = V1,
    entity_type: str | None = "HostSystem",
) -> TimelineEntry:
    return TimelineEntry(
        kind="event",
        source_id=source_id,
        timestamp_utc=_at(minute),
        level=level,  # type: ignore[arg-type]
        title=event_type,
        detail=f"msg-{source_id}",
        entity_name=entity,
        entity_type=entity_type,
        vcenter_id=vcenter_id,
        score=score,
        merge_key=("event", event_type, entity, vcenter_id, level),
        ref={"event_id": source_id, "event_type": event_type},
    )


def _alert(
    source_id: int,
    minute: float,
    *,
    level: str = "warning",
    entity: str | None = None,
    state: str = "firing",
    vcenter_id: uuid.UUID | None = None,
) -> TimelineEntry:
    return TimelineEntry(
        kind="alert",
        source_id=source_id,
        timestamp_utc=_at(minute),
        level=alert_level(level, state),
        title=alert_title(f"rule-{source_id}", state),
        entity_name=entity,
        vcenter_id=vcenter_id,
        is_signal=state == "firing",
        ref={"alert_history_id": source_id, "alert_state": state},
    )


# --- バケット ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("span", "expected"),
    [
        (timedelta(minutes=15), 10),
        (timedelta(minutes=29), 15),
        (timedelta(minutes=30), 60),
        (timedelta(hours=1), 60),
        (timedelta(hours=2), 60),
        (timedelta(hours=6), 300),
        (timedelta(hours=24), 900),
        (timedelta(days=7), 2 * 3600),
        (timedelta(days=90), 86400),
    ],
)
def test_choose_bucket_seconds_picks_round_width(span: timedelta, expected: int) -> None:
    assert choose_bucket_seconds(T0, T0 + span) == expected


@pytest.mark.parametrize(
    "span",
    [timedelta(seconds=s) for s in (30, 61, 599, 3601, 7 * 3600 + 13, 3 * 86400 + 1)]
    + [timedelta(days=d) for d in (1, 13, 45, 90)],
)
def test_choose_bucket_seconds_keeps_bar_count_between_30_and_120(span: timedelta) -> None:
    width = choose_bucket_seconds(T0, T0 + span)
    n = overview_bucket_count(T0, T0 + span, width)
    assert 30 <= n <= 120


def test_choose_bucket_seconds_rejects_empty_range() -> None:
    with pytest.raises(ValueError):
        choose_bucket_seconds(T0, T0)


def test_last_bucket_covers_remainder_when_span_is_not_divisible() -> None:
    to = T0 + timedelta(minutes=10, seconds=30)
    width = 60
    n = overview_bucket_count(T0, to, width)
    assert n == 11
    buckets = build_overview(T0, width, n, {"event_total": [0] * 10 + [2]})
    starts = [b.bucket_start_utc for b in buckets]
    assert starts[0] == T0
    assert starts[-1] < to <= starts[-1] + timedelta(seconds=width)
    assert buckets[-1].event_total == 2
    # counts に無い種別は 0
    assert all(b.alert == 0 and b.metric_breach == 0 and b.log_error == 0 for b in buckets)


def test_bucket_index_truncates_to_second_like_the_database() -> None:
    assert bucket_index(T0 + timedelta(seconds=59, microseconds=999_999), T0, 60) == 0
    assert bucket_index(T0 + timedelta(seconds=60), T0, 60) == 1


def test_count_per_bucket_ignores_out_of_range() -> None:
    counts = count_per_bucket(
        [T0 - timedelta(seconds=1), T0, _at(1.5), _at(3)], T0, 60, 3
    )
    assert counts == [1, 1, 0]


# --- level・タイトル ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "severity", "expected"),
    [
        (80, None, "critical"),
        (79, None, "error"),
        (60, None, "error"),
        (59, None, "warning"),
        (40, None, "warning"),
        (39, None, "info"),
        (0, "ERROR", "error"),
        (0, " Warning ", "warning"),
        (90, "warning", "critical"),
        (0, "info", "info"),
        (0, "user", "info"),
    ],
)
def test_event_level(score: int, severity: str | None, expected: str) -> None:
    assert event_level(score, severity) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("critical", "critical"), ("error", "error"), ("warning", "warning"), ("info", "warning"), (None, "warning"), ("bogus", "warning")],
)
def test_alert_level(value: str | None, expected: str) -> None:
    assert alert_level(value, "firing") == expected


@pytest.mark.parametrize(
    ("value", "state", "expected"),
    [
        ("critical", "resolved", "info"),
        ("warning", "resolved", "info"),
        ("critical", "stale", "warning"),
        ("warning", "stale", "warning"),
        ("critical", "something-else", "info"),
    ],
)
def test_alert_level_is_capped_unless_firing(value: str, state: str, expected: str) -> None:
    """履歴の alert_level は回復の通知でもルールの level なので、firing 以外は上限をかける。"""
    assert alert_level(value, state) == expected


def test_alert_title_uses_alert_history_panel_wording() -> None:
    assert alert_title("CPU 高負荷", "firing") == "CPU 高負荷 が発火"
    assert alert_title("CPU 高負荷", "resolved") == "CPU 高負荷 が回復"
    assert alert_title("CPU 高負荷", "stale") == "CPU 高負荷 のデータが古い"


def test_entity_matches_is_case_insensitive_substring() -> None:
    assert entity_matches("esx-Alpha-01", "ALPHA")
    assert not entity_matches("vm-beta", "alpha")
    assert not entity_matches(None, "alpha")
    # ワイルドカードは文字どおり
    assert not entity_matches("esx01", "esx%")
    assert entity_matches("esx_01", "x_0")


# --- 並べ替え・まとめ --------------------------------------------------------------------


def test_same_timestamp_orders_alert_before_event_then_by_source_id() -> None:
    entries = [_ev(5, 1), _ev(3, 1, "B"), _alert(9, 1), _alert(2, 1), _ev(1, 0)]
    assert [e.item_id for e in sort_entries(entries)] == [
        "event:1", "alert:2", "alert:9", "event:3", "event:5",
    ]


def test_three_or_more_consecutive_events_are_merged() -> None:
    entries = [
        _ev(1, 1, score=60, level="error"),
        _ev(2, 2, score=75, level="error"),
        _ev(3, 3, score=65, level="error"),
        _ev(4, 4, score=70, level="error"),
    ]
    (merged,) = merge_consecutive(entries)
    assert merged.count == 4
    assert merged.timestamp_utc == _at(1)
    assert merged.end_utc == _at(4)
    assert merged.score == 75
    assert merged.level == "error"
    assert merged.detail == "msg-1"
    assert merged.item_id == "event:1"
    assert merged.ref["event_id"] == 1
    assert merged.to_item().end_utc == _at(4)


def test_single_item_has_no_end() -> None:
    (only,) = merge_consecutive([_ev(1, 1)])
    assert only.end_utc is None and only.count == 1


def test_same_name_on_different_vcenters_is_not_merged() -> None:
    merged = merge_consecutive([_ev(1, 1, vcenter_id=V1), _ev(2, 2, vcenter_id=V2)])
    assert [m.count for m in merged] == [1, 1]


def test_events_without_entity_name_are_merged_with_each_other() -> None:
    merged = merge_consecutive([_ev(1, 1, entity=None), _ev(2, 2, entity=None), _ev(3, 3, entity="h1")])
    assert [(m.entity_name, m.count) for m in merged] == [(None, 2), ("h1", 1)]


def test_alerts_are_never_merged_and_break_event_runs() -> None:
    merged = merge_consecutive(sort_entries([_ev(1, 1), _alert(7, 2), _alert(8, 2), _ev(2, 3)]))
    assert [(m.item_id, m.count) for m in merged] == [
        ("event:1", 1), ("alert:7", 1), ("alert:8", 1), ("event:2", 1),
    ]


# --- 打ち切り ----------------------------------------------------------------------------


def test_within_limit_is_not_truncated() -> None:
    entries = [_ev(1, 1), _ev(2, 2, "B")]
    kept, truncated = select_within_limit(entries, 2, None)
    assert kept == entries and truncated is False


def test_truncation_without_anchor_prefers_level_then_score_then_newer() -> None:
    entries = [
        _ev(1, 1, "A", score=50, level="warning"),
        _ev(2, 2, "B", score=10, level="error"),   # level が重い
        _ev(3, 3, "C", score=55, level="warning"),  # 同じ level で score が高い
        _ev(4, 4, "D", score=50, level="warning"),  # 1 と同点で新しい
    ]
    kept, truncated = select_within_limit(entries, 3, None)
    assert truncated is True
    assert [e.item_id for e in kept] == ["event:2", "event:3", "event:4"]  # 時刻順に並べ直す


def test_truncation_with_anchor_is_deterministic_for_equal_distance() -> None:
    anchor = _at(10)
    before = _ev(1, 9, "A", score=30, level="info")
    after = _ev(2, 11, "B", score=30, level="info")
    far = _ev(3, 20, "C", score=99, level="critical")
    entries = [before, after, far]
    # 同じ距離・同じ level・同じ score なら新しいほう
    kept, _ = select_within_limit(entries, 1, anchor)
    assert [e.item_id for e in kept] == ["event:2"]
    # 入力の順を変えても同じ
    kept_again, _ = select_within_limit(list(reversed(entries)), 1, anchor)
    assert [e.item_id for e in kept_again] == ["event:2"]
    # 同じ距離なら level が重いほう
    heavier_before = _ev(1, 9, "A", score=30, level="error")
    kept, _ = select_within_limit([heavier_before, after, far], 1, anchor)
    assert [e.item_id for e in kept] == ["event:1"]


def test_truncation_with_anchor_tie_on_everything_falls_back_to_input_order() -> None:
    anchor = _at(10)
    a = _ev(1, 11, "A")
    b = _ev(2, 11, "B")
    kept, _ = select_within_limit(sort_entries([b, a]), 1, anchor)
    assert [e.item_id for e in kept] == ["event:1"]


# --- ハイライト --------------------------------------------------------------------------


def test_first_signal_is_earliest_warning_or_above() -> None:
    entries = sort_entries([_ev(1, 1, level="info"), _ev(2, 5, "B", level="warning"), _alert(3, 3, level="critical")])
    sig = first_signal(entries)
    assert sig is not None and sig.item_id == "alert:3"
    assert first_signal([_ev(1, 1, level="info")]) is None


def test_top_entities_sum_merged_counts_and_break_ties_by_first_seen() -> None:
    merged = merge_consecutive(
        sort_entries(
            [
                _ev(1, 1, "A", "h1"),
                _ev(2, 2, "A", "h1"),
                _ev(3, 3, "A", "h1"),  # h1: まとめて count=3
                _ev(4, 4, "B", "h2"),
                _ev(5, 5, "C", "h2"),
                _ev(6, 6, "D", "h2"),  # h2: 3 件、h1 より遅い
                _ev(7, 7, "E", "h3", entity_type=None),
                _ev(8, 8, "F", "h3"),  # h3: 2 件、entity_type は後から分かる
                _ev(9, 9, "G", None),  # 対象なしは数えない
                _alert(10, 10, entity="h4"),
            ]
        )
    )
    top = top_entities(merged)
    assert [(t.entity_name, t.item_count) for t in top] == [("h1", 3), ("h2", 3), ("h3", 2), ("h4", 1)]
    assert top[0].vcenter_id == V1 and top[3].vcenter_id is None
    assert top[0].first_seen_utc == _at(1)
    assert top[2].entity_type == "HostSystem"
    assert len(top_entities(merged, limit=2)) == 2


def test_summarize_and_pick_new_event_types() -> None:
    stats = summarize_event_types(
        [
            _ev(1, 1, "Old", score=30),
            _ev(2, 2, "New", score=70),
            _ev(3, 3, "New", score=55),
            _ev(4, 4, "Other", score=70),
            _alert(5, 5),
        ]
    )
    assert stats["New"] == EventTypeStats(event_type="New", count=2, first_seen_utc=_at(2), max_score=70)
    picked = pick_new_event_types(stats, {"Old"})
    # max_score 降順、同点は最初の時刻の昇順
    assert [(p.event_type, p.count, p.max_score) for p in picked] == [("New", 2, 70), ("Other", 1, 70)]
    assert len(pick_new_event_types(stats, set(), limit=1)) == 1



# --- レビュー指摘への対応 ---------------------------------------------------------------


def test_resolved_alert_is_not_first_signal_and_does_not_win_truncation() -> None:
    resolved = _alert(1, 1, level="critical", state="resolved")
    warn = _ev(5, 5, "W", score=45, level="warning")
    err = _ev(6, 6, "E", score=70, level="error")
    entries = sort_entries([resolved, warn, err])
    assert resolved.level == "info"
    sig = first_signal(entries)
    assert sig is not None and sig.item_id == "event:5"
    kept, _ = select_within_limit(entries, 1, None)
    assert [k.item_id for k in kept] == ["event:6"]


def test_stale_alert_is_capped_at_warning_and_is_not_a_signal() -> None:
    stale = _alert(1, 1, level="critical", state="stale")
    assert stale.level == "warning"
    assert first_signal([stale]) is None


def test_events_with_different_levels_are_not_merged() -> None:
    merged = merge_consecutive(
        sort_entries([_ev(1, 1, score=10, level="info"), _ev(2, 50, score=90, level="critical")])
    )
    assert [(m.item_id, m.level, m.count) for m in merged] == [("event:1", "info", 1), ("event:2", "critical", 1)]
    sig = first_signal(merged)
    assert sig is not None and sig.timestamp_utc == _at(50)


def test_merge_stops_when_gap_exceeds_max_gap() -> None:
    entries = [_ev(1, 0), _ev(2, 5), _ev(3, 10), _ev(4, 16)]
    merged = merge_consecutive(entries, max_gap=timedelta(minutes=5))
    # 0→5→10 は間隔ちょうど 5 分でまとまり、10→16 は 6 分空くので別の行
    assert [(m.item_id, m.count, m.end_utc) for m in merged] == [
        ("event:1", 3, _at(10)),
        ("event:4", 1, None),
    ]
    # 指定しなければ間隔で切らない
    assert len(merge_consecutive(entries)) == 1


def test_anchor_inside_a_merged_run_has_zero_distance() -> None:
    run = merge_consecutive([_ev(i, i) for i in range(60)])
    assert len(run) == 1 and run[0].end_utc == _at(59)
    others = [_ev(100 + i, 61 + i * 0.1, f"B{i}", f"x{i}") for i in range(3)]
    entries = sort_entries([*run, *others])
    kept, truncated = select_within_limit(entries, 1, _at(58))
    assert truncated is True
    assert [k.item_id for k in kept] == ["event:0"]


def test_top_entities_count_same_name_on_each_vcenter_separately() -> None:
    entries = sort_entries(
        [
            _ev(1, 1, "A", "esx01", vcenter_id=V1),
            _ev(2, 2, "B", "esx01", vcenter_id=V2),
            _ev(3, 3, "C", "esx01", vcenter_id=V2),
        ]
    )
    entries = [replace(e, vcenter_name=f"vc-{e.vcenter_id.int}") for e in entries]  # type: ignore[union-attr]
    top = top_entities(entries)
    assert [(t.entity_name, t.vcenter_id, t.item_count, t.vcenter_name) for t in top] == [
        ("esx01", V2, 2, "vc-2"),
        ("esx01", V1, 1, "vc-1"),
    ]


def test_truncation_without_anchor_keeps_alert_before_event_of_same_level() -> None:
    event = _ev(1, 1, "A", score=95, level="critical")
    alert = _alert(2, 2, level="critical")
    kept, _ = select_within_limit(sort_entries([event, alert]), 1, None)
    assert [k.item_id for k in kept] == ["alert:2"]
    # level が重いイベントはアラートより先
    heavier = _ev(3, 3, "B", score=95, level="critical")
    warn_alert = _alert(4, 4, level="warning")
    kept, _ = select_within_limit(sort_entries([heavier, warn_alert]), 1, None)
    assert [k.item_id for k in kept] == ["event:3"]
