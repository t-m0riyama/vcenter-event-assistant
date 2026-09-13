"""カーソルの規則。取りこぼしと読み直しの両方を防ぐ。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from vcenter_event_assistant_plugin_api.cursors import TimestampCursor

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
CURSOR = "2026-01-01T00:00:00+00:00"


def test_decode_reads_an_iso_timestamp() -> None:
    assert TimestampCursor().decode(CURSOR) == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_decode_treats_missing_cursor_as_first_run() -> None:
    assert TimestampCursor().decode(None) is None
    assert TimestampCursor().decode("") is None


def test_decode_treats_a_broken_cursor_as_first_run() -> None:
    """壊れたカーソルで収集全体を落とすより、初回として扱う方が回復しやすい。"""
    assert TimestampCursor().decode("not-a-timestamp") is None


def test_window_start_steps_back_by_the_overlap() -> None:
    """境界上のイベントを取りこぼさないための重ね読み。"""
    assert TimestampCursor().window_start(CURSOR) == datetime(
        2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc
    )


def test_overlap_is_configurable() -> None:
    cursor = TimestampCursor(overlap=timedelta(minutes=5))
    assert cursor.window_start(CURSOR) == datetime(
        2025, 12, 31, 23, 55, tzinfo=timezone.utc
    )


def test_window_start_is_none_without_a_cursor_or_a_lookback() -> None:
    """初回の範囲は取得側の既定に委ねる。"""
    assert TimestampCursor().window_start(None) is None


def test_window_start_uses_the_lookback_when_configured() -> None:
    cursor = TimestampCursor(default_lookback=timedelta(days=1))
    assert cursor.window_start(None, now=NOW) == NOW - timedelta(days=1)


def test_advance_uses_the_newest_event() -> None:
    newest = datetime(2026, 2, 1, tzinfo=timezone.utc)
    assert TimestampCursor().advance(CURSOR, newest) == newest.isoformat()


def test_advance_keeps_the_previous_cursor_on_an_empty_batch() -> None:
    """前進しないと同じ範囲を読み続ける。ここで値を返さないのが最悪の選択。"""
    assert TimestampCursor().advance(CURSOR, None) == CURSOR


def test_advance_falls_back_to_now_on_the_very_first_empty_batch() -> None:
    assert TimestampCursor().advance(None, None, now=NOW) == NOW.isoformat()


def test_advance_always_returns_a_value() -> None:
    for previous in (None, "", CURSOR):
        assert TimestampCursor().advance(previous, None, now=NOW)


def test_a_cursor_round_trips_through_window_start() -> None:
    """advance した値を次回 window_start に渡せること。"""
    cursor = TimestampCursor()
    newest = datetime(2026, 3, 1, 10, 30, tzinfo=timezone.utc)
    encoded = cursor.advance(None, newest)
    assert cursor.window_start(encoded) == newest - timedelta(seconds=1)
