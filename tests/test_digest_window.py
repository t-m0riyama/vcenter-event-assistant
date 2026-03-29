"""digest_window の集計ウィンドウ（UTC 互換と IANA 指定）の境界テスト。"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from vcenter_event_assistant.services.digest_window import (
    utc_previous_calendar_month_window,
    utc_previous_week_window,
    utc_yesterday_window,
    zoned_previous_calendar_month_window,
    zoned_previous_week_window,
    zoned_yesterday_window,
)

_TOKYO = ZoneInfo("Asia/Tokyo")


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


def test_previous_calendar_month_mid_march() -> None:
    now = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
    fr, to = utc_previous_calendar_month_window(now)
    assert fr == datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert to == datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_previous_calendar_month_on_first_of_month() -> None:
    now = datetime(2026, 3, 1, 8, 0, 0, tzinfo=timezone.utc)
    fr, to = utc_previous_calendar_month_window(now)
    assert fr == datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert to == datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_previous_calendar_month_leap_year() -> None:
    now = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
    fr, to = utc_previous_calendar_month_window(now)
    assert fr == datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert to == datetime(2024, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_previous_calendar_month_year_boundary() -> None:
    now = datetime(2026, 1, 10, 0, 0, 0, tzinfo=timezone.utc)
    fr, to = utc_previous_calendar_month_window(now)
    assert fr == datetime(2025, 12, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert to == datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_zoned_yesterday_tokyo_crosses_utc_date() -> None:
    """2026-03-22 15:00 UTC は JST では 3/23 0:00。昨日は JST 3/22 一日分。"""
    now = datetime(2026, 3, 22, 15, 0, 0, tzinfo=timezone.utc)
    fr, to = zoned_yesterday_window(now, _TOKYO)
    assert fr == datetime(2026, 3, 21, 15, 0, 0, tzinfo=timezone.utc)
    assert to == datetime(2026, 3, 22, 15, 0, 0, tzinfo=timezone.utc)


def test_zoned_previous_week_tokyo() -> None:
    """JST 3/25 21:00 時点で直前週は JST 3/15 0:00〜3/22 0:00。"""
    now = datetime(2026, 3, 25, 12, 0, 0, tzinfo=timezone.utc)
    fr, to = zoned_previous_week_window(now, _TOKYO)
    assert fr == datetime(2026, 3, 14, 15, 0, 0, tzinfo=timezone.utc)
    assert to == datetime(2026, 3, 21, 15, 0, 0, tzinfo=timezone.utc)


def test_zoned_previous_month_tokyo() -> None:
    """JST 3/15 21:00 時点の直前暦月は 2/1〜3/1（JST 0:00 境界）。"""
    now = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
    fr, to = zoned_previous_calendar_month_window(now, _TOKYO)
    assert fr == datetime(2026, 1, 31, 15, 0, 0, tzinfo=timezone.utc)
    assert to == datetime(2026, 2, 28, 15, 0, 0, tzinfo=timezone.utc)
