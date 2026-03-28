"""digest_window の UTC 集計ウィンドウの境界テスト。"""

from __future__ import annotations

from datetime import datetime, timezone

from vcenter_event_assistant.services.digest_window import (
    utc_previous_week_window,
    utc_yesterday_window,
)


def test_yesterday_window_mid_march() -> None:
    now = datetime(2026, 3, 23, 7, 30, 0, tzinfo=timezone.utc)
    fr, to = utc_yesterday_window(now)
    assert fr == datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    assert to == datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
    assert fr < to


def test_previous_week_window_wednesday() -> None:
    now = datetime(2026, 3, 25, 12, 0, 0, tzinfo=timezone.utc)
    fr, to = utc_previous_week_window(now)
    assert fr == datetime(2026, 3, 15, 0, 0, 0, tzinfo=timezone.utc)
    assert to == datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
    assert fr < to


def test_previous_week_window_sunday() -> None:
    now = datetime(2026, 3, 22, 10, 0, 0, tzinfo=timezone.utc)
    fr, to = utc_previous_week_window(now)
    assert fr == datetime(2026, 3, 15, 0, 0, 0, tzinfo=timezone.utc)
    assert to == datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)


def test_previous_week_window_monday() -> None:
    now = datetime(2026, 3, 23, 0, 0, 0, tzinfo=timezone.utc)
    fr, to = utc_previous_week_window(now)
    assert fr == datetime(2026, 3, 15, 0, 0, 0, tzinfo=timezone.utc)
    assert to == datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)


def test_previous_week_window_saturday_late_changes_week_anchor() -> None:
    """土曜深夜は当該週の日曜が先週の日曜になる。"""
    now = datetime(2026, 3, 21, 23, 59, 0, tzinfo=timezone.utc)
    fr, to = utc_previous_week_window(now)
    assert to == datetime(2026, 3, 15, 0, 0, 0, tzinfo=timezone.utc)
    assert fr == datetime(2026, 3, 8, 0, 0, 0, tzinfo=timezone.utc)


def test_previous_week_window_sunday_after_midnight_anchor() -> None:
    now = datetime(2026, 3, 22, 0, 1, 0, tzinfo=timezone.utc)
    fr, to = utc_previous_week_window(now)
    assert to == datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
    assert fr == datetime(2026, 3, 15, 0, 0, 0, tzinfo=timezone.utc)
