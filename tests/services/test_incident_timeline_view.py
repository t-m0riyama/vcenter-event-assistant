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
    count_spans_per_bucket,
    entity_matches,
    event_level,
    first_signal,
    log_level,
    merge_consecutive,
    metric_breach_detail,
    metric_breach_level,
    metric_breach_title,
    format_number,
    overview_bucket_count,
    pick_new_event_types,
    select_within_limit,
    sort_entries,
    summarize_event_types,
    top_entities,
    truncate_detail,
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


# --- PR4: 種別の優先（メトリクス・ログ） --------------------------------------------------


def _bare(kind: str, source_id: int, minute: float, level: str = "error") -> TimelineEntry:
    return TimelineEntry(
        kind=kind,  # type: ignore[arg-type]
        source_id=source_id,
        timestamp_utc=_at(minute),
        level=level,  # type: ignore[arg-type]
        title=f"{kind}-{source_id}",
    )


def test_truncation_without_anchor_orders_kinds_alert_event_metric_log() -> None:
    """同じ level なら、アラート → イベント → メトリクス → ログの順に残す（時刻やスコアより先）。"""
    # ログを最も新しくしても、メトリクスより後に回る（新しい順の規則より種別が先）
    log = _bare("log", 1, 8)
    metric = _bare("metric", 2, 2)
    event = replace(_ev(3, 3, "A", score=0, level="error"))
    alert = _alert(4, 0, level="error")
    entries = sort_entries([log, metric, event, alert])
    for limit, expected in (
        (1, ["alert:4"]),
        (2, ["alert:4", "event:3"]),
        (3, ["alert:4", "metric:2", "event:3"]),
    ):
        kept, _ = select_within_limit(entries, limit, None)
        assert sorted(k.item_id for k in kept) == sorted(expected)
    # level が重いログは、ログの上限（枠の半分）の中では軽いアラートより先
    heavy_log = _bare("log", 9, 9, level="critical")
    light_alert = _alert(5, 5, level="warning")
    kept, _ = select_within_limit(sort_entries([alert, light_alert, heavy_log]), 2, None)
    assert sorted(k.item_id for k in kept) == ["alert:4", "log:9"]
    # 枠が 1 ならログの上限は 0（ほかの種別で埋まる）
    kept, _ = select_within_limit(sort_entries([alert, heavy_log]), 1, None)
    assert [k.item_id for k in kept] == ["alert:4"]


def test_truncation_with_anchor_uses_distance_before_kind() -> None:
    """anchor があるときは種別より距離。区間の中に anchor があるメトリクスは距離 0。"""
    alert = _alert(1, 0, level="error")
    metric = replace(_bare("metric", 2, 5), end_utc=_at(15))
    kept, _ = select_within_limit(sort_entries([alert, metric]), 1, _at(10))
    assert [k.item_id for k in kept] == ["metric:2"]


def test_same_timestamp_orders_alert_event_metric_log() -> None:
    entries = sort_entries([_bare("log", 1, 1), _bare("metric", 2, 1), _ev(3, 1), _alert(4, 1)])
    assert [e.kind for e in entries] == ["alert", "event", "metric", "log"]


# --- PR4: メトリクスの超過区間 ------------------------------------------------------------


@pytest.mark.parametrize(
    ("peak", "threshold", "expected"),
    [
        (80, 80, "warning"),
        (94.99, 80, "warning"),
        (95, 80, "error"),
        (100, 99, "error"),
        (74.99, 60, "warning"),
        (75, 60, "error"),
        (20, 5, "error"),
    ],
)
def test_metric_breach_level(peak: float, threshold: float, expected: str) -> None:
    assert metric_breach_level(peak, threshold) == expected


def test_metric_breach_title_and_detail() -> None:
    assert metric_breach_title("host.cpu.usage_pct", 80.0) == "CPU 使用率が閾値（80%）を超過"
    assert metric_breach_title("host.mem.usage_pct", 85.5) == "メモリ使用率が閾値（85.5%）を超過"
    # 時刻は detail に書かない（画面が ref.peak_at_utc を設定のタイムゾーンで表示する）
    assert metric_breach_detail(92.346, 3, continued=False) == "ピーク 92.35%、サンプル 3 件"
    assert metric_breach_detail(90.0, 1, continued=True) == "ピーク 90%、サンプル 1 件、期間の開始前から継続"


def test_count_spans_per_bucket_counts_every_touched_bucket_and_clips() -> None:
    spans = [
        (_at(1), _at(3)),        # 1, 2, 3
        (_at(2.5), None),        # 2 だけ
        (_at(-5), _at(0.5)),     # 期間の前から: 0 だけ
        (_at(8), _at(30)),       # 期間の後ろへはみ出す: 8, 9
    ]
    assert count_spans_per_bucket(spans, T0, 60, 10) == [1, 1, 2, 1, 0, 0, 0, 0, 1, 1]


# --- PR4: エラーログ ----------------------------------------------------------------------


def test_truncate_detail() -> None:
    assert truncate_detail(None) is None
    assert truncate_detail("") is None
    assert truncate_detail("abc", 3) == "abc"
    assert truncate_detail("abcd", 3) == "abc…"
    assert truncate_detail("x" * 1001) == "x" * 1000 + "…"


def test_log_runs_merge_only_with_the_same_source_and_within_gap() -> None:
    def log(source_id: int, minute: float, host: str = "esx01", kind: str = "vmkernel") -> TimelineEntry:
        return TimelineEntry(
            kind="log", source_id=source_id, timestamp_utc=_at(minute), level="error",
            title=f"{host} {kind}", entity_name=host, vcenter_id=V1,
            merge_key=("log", V1, host, kind, "error"), ref={"log_id": source_id},
        )

    merged = merge_consecutive(
        sort_entries([log(1, 0), log(2, 1), log(3, 2, kind="hostd"), log(4, 3), log(5, 9)]),
        max_gap=timedelta(minutes=5),
    )
    assert [(m.item_id, m.count, m.end_utc) for m in merged] == [
        ("log:1", 2, _at(1)), ("log:3", 1, None), ("log:4", 1, None), ("log:5", 1, None),
    ]


@pytest.mark.parametrize(
    ("severity", "expected"),
    [
        ("error", "warning"), ("ERR", "warning"), (" Error ", "warning"),
        ("critical", "error"), ("crit", "error"), ("FATAL", "error"), ("panic", "error"),
        ("alert", "error"), ("emerg", "error"),
        ("warning", None), ("info", None), ("", None), (None, None), ("errors", None),
    ],
)
def test_log_level(severity: str | None, expected: str | None) -> None:
    assert log_level(severity) == expected


# --- 打ち切り: ログは枠の半分まで（anchor なし） -----------------------------------------


def _many(kind: str, start_id: int, n: int, level: str, minute0: float = 0) -> list[TimelineEntry]:
    return [_bare(kind, start_id + i, minute0 + i * 0.1, level=level) for i in range(n)]


def test_truncation_caps_logs_at_half_when_logs_are_many() -> None:
    """ログが多いとき、level が重くても枠の半分（切り捨て）までしか占めない。残りはほかの種別。"""
    logs = _many("log", 1000, 20, "error")
    metrics = _many("metric", 1, 20, "warning", minute0=10)
    kept, truncated = select_within_limit(sort_entries([*logs, *metrics]), 7, None)
    assert truncated is True
    assert [e.kind for e in kept].count("log") == 3  # 7 // 2
    assert [e.kind for e in kept].count("metric") == 4
    # ログの中では今までどおりの優先（同じ level・score なら新しい順）
    assert {e.source_id for e in kept if e.kind == "log"} == {1017, 1018, 1019}
    # ほかの種別の中も今までどおり（新しい順）
    assert {e.source_id for e in kept if e.kind == "metric"} == {17, 18, 19, 20}


def test_truncation_keeps_few_logs_by_the_usual_priority() -> None:
    """ログが半分より少ないときは、ログも今までどおりの優先で選ぶ（枠を取り置かない）。"""
    logs = [_bare("log", 1000, 1, level="error"), _bare("log", 1001, 2, level="info")]
    metrics = _many("metric", 1, 10, "warning", minute0=10)
    kept, _ = select_within_limit(sort_entries([*logs, *metrics]), 6, None)
    # error のログは残り、info のログは warning のメトリクスに負ける
    assert sorted(e.item_id for e in kept if e.kind == "log") == ["log:1000"]
    assert len([e for e in kept if e.kind == "metric"]) == 5


def test_truncation_fills_spare_slots_with_logs_when_other_kinds_are_few() -> None:
    """ほかの種別だけでは枠が埋まらないときは、余った枠をログで埋める。"""
    logs = _many("log", 1000, 20, "warning")
    alerts = [_alert(1, 1, level="warning")]
    kept, truncated = select_within_limit(sort_entries([*logs, *alerts]), 10, None)
    assert truncated is True and len(kept) == 10
    assert [e.kind for e in kept].count("log") == 9
    assert "alert:1" in {e.item_id for e in kept}
    # ログしか無い期間でも、枠いっぱいまで返す
    kept, _ = select_within_limit(sort_entries(logs), 10, None)
    assert len(kept) == 10


def test_truncation_with_anchor_does_not_cap_logs() -> None:
    logs = _many("log", 1000, 10, "warning", minute0=30)
    metrics = _many("metric", 1, 10, "warning", minute0=0)
    kept, _ = select_within_limit(sort_entries([*logs, *metrics]), 6, _at(30.5))
    assert all(e.kind == "log" for e in kept)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (80, "80"), (80.0, "80"), (82.5, "82.5"), (82.55, "82.55"), (82.50, "82.5"),
        (0.5, "0.5"), (0, "0"), (99.999, "100"), (92.346, "92.35"), (0.001, "0"),
        (1234567.0, "1234567"), (12.10, "12.1"),
    ],
)
def test_format_number_uses_up_to_two_decimals_without_trailing_zeros(value: float, expected: str) -> None:
    """画面と揃える規則: 小数は 2 桁まで（丸める）、末尾の 0 と小数点は書かない。"""
    assert format_number(value) == expected


def test_metric_title_and_detail_use_the_shared_number_format() -> None:
    assert metric_breach_title("host.cpu.usage_pct", 82.55) == "CPU 使用率が閾値（82.55%）を超過"
    assert metric_breach_detail(82.549, 2, continued=False) == "ピーク 82.55%、サンプル 2 件"


def test_top_entities_count_a_merged_log_row_as_one() -> None:
    """ログはまとめた行を 1 件として数える（エラーを大量に出すホストが上位を占めないように）。
    イベントは今までどおり、まとめる前の件数で数える。"""
    def log(source_id: int, minute: float, host: str) -> TimelineEntry:
        return TimelineEntry(
            kind="log", source_id=source_id, timestamp_utc=_at(minute), level="warning",
            title=f"{host} vmkernel", entity_name=host, entity_type="host", vcenter_id=V1,
            merge_key=("log", V1, host, "vmkernel", "warning"), ref={"log_id": source_id},
        )

    merged = merge_consecutive(
        sort_entries(
            [
                *[log(100 + i, i * 0.1, "noisy") for i in range(50)],  # まとめて 1 行（count=50）
                _ev(1, 10, "A", "h1"), _ev(2, 11, "A", "h1"), _ev(3, 12, "A", "h1"),  # まとめて count=3
            ]
        )
    )
    assert [(m.kind, m.count) for m in merged] == [("log", 50), ("event", 3)]
    top = top_entities(merged)
    assert [(t.entity_name, t.item_count) for t in top] == [("h1", 3), ("noisy", 1)]
