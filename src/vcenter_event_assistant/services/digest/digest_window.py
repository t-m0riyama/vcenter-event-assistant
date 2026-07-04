"""ダイジェスト集計ウィンドウの半開区間 ``[from, to)``（``to`` は含まない）。境界は IANA タイムゾーン上の暦で解釈する。"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from zoneinfo import ZoneInfo

_UTC_ZONE = ZoneInfo("UTC")


def _to_utc_instant(n: datetime | None) -> datetime:
    """``now`` を UTC の timezone-aware 瞬間に正規化する。"""
    t = n or datetime.now(timezone.utc)
    if t.tzinfo is None:
        return t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc)


def zoned_yesterday_window(now: datetime | None, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """
    直前の **指定タイムゾーンの暦日** ``[昨日 0:00, 今日 0:00)`` を UTC 瞬間で返す。

    例: ``Asia/Tokyo`` かつ ``now`` が JST で 3/23 なら、JST 3/22 一日分。
    """
    n = _to_utc_instant(now)
    local = n.astimezone(tz)
    d = local.date()
    from_local = datetime.combine(d - timedelta(days=1), time.min, tzinfo=tz)
    to_local = datetime.combine(d, time.min, tzinfo=tz)
    return from_local.astimezone(timezone.utc), to_local.astimezone(timezone.utc)


def zoned_previous_week_window(now: datetime | None, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """
    直前に完了した **指定 TZ・日曜 0:00 始まり** の暦週の半開区間 ``[from, to)``（ちょうど 7 日）。

    ``to`` は ``now`` のローカル暦日が属する週の日曜 0:00（その TZ）、``from`` はその 7 日前。
    Python の ``weekday()`` は月曜=0 … 日曜=6。
    """
    n = _to_utc_instant(now)
    local = n.astimezone(tz)
    start_today = datetime.combine(local.date(), time.min, tzinfo=tz)
    days_since_sunday = (start_today.weekday() + 1) % 7
    this_week_sunday = start_today - timedelta(days=days_since_sunday)
    prev_week_start = this_week_sunday - timedelta(days=7)
    return prev_week_start.astimezone(timezone.utc), this_week_sunday.astimezone(timezone.utc)


def zoned_previous_calendar_month_window(now: datetime | None, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """
    直前の **指定 TZ の暦月**の半開区間 ``[from, to)`` を UTC で返す。

    ``to`` は ``now`` のローカル暦日が含まれる月の 1 日 0:00（その TZ）、
    ``from`` はその直前の月の 1 日 0:00（その TZ）。
    """
    n = _to_utc_instant(now)
    local = n.astimezone(tz)
    start_today = datetime.combine(local.date(), time.min, tzinfo=tz)
    first_this_month = start_today.replace(day=1)
    last_day_prev_month = first_this_month - timedelta(days=1)
    first_prev_month = last_day_prev_month.replace(day=1)
    return first_prev_month.astimezone(timezone.utc), first_this_month.astimezone(timezone.utc)


def utc_yesterday_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """
    直前の UTC 暦日 ``[00:00, 翌日 00:00)`` を返す。

    例: 現在が 2026-03-23 07:00 UTC なら ``2026-03-22 00:00 UTC`` 〜 ``2026-03-23 00:00 UTC``。
    """
    return zoned_yesterday_window(now, _UTC_ZONE)


def utc_previous_week_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """
    直前に完了した **UTC・日曜 0:00 始まり** の暦週の半開区間 ``[from, to)`` を返す（ちょうど 7 日）。

    ``to`` は ``now`` の暦日が属する週の日曜 0:00 UTC、``from`` はその 7 日前。
    Python の ``weekday()`` は月曜=0 … 日曜=6。
    """
    return zoned_previous_week_window(now, _UTC_ZONE)


def utc_previous_calendar_month_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """
    直前の **UTC 暦月**の半開区間 ``[from, to)`` を返す。

    ``to`` は ``now`` の暦日が含まれる月の 1 日 0:00 UTC、``from`` はその直前の月の 1 日 0:00 UTC。
    """
    return zoned_previous_calendar_month_window(now, _UTC_ZONE)
