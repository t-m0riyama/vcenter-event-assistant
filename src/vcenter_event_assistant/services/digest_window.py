"""ダイジェスト集計ウィンドウ（UTC）のヘルパー。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def utc_yesterday_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """
    直前の UTC 暦日 ``[00:00, 翌日 00:00)`` を返す。

    例: 現在が 2026-03-23 07:00 UTC なら ``2026-03-22 00:00 UTC`` 〜 ``2026-03-23 00:00 UTC``。
    """
    n = now or datetime.now(timezone.utc)
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)
    else:
        n = n.astimezone(timezone.utc)
    today_start = n.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    return yesterday_start, today_start


def utc_previous_week_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """
    直前に完了した **UTC・日曜 0:00 始まり** の暦週の半開区間 ``[from, to)`` を返す（ちょうど 7 日）。

    ``to`` は ``now`` の暦日が属する週の日曜 0:00 UTC、``from`` はその 7 日前。
    Python の ``weekday()`` は月曜=0 … 日曜=6。
    """
    n = now or datetime.now(timezone.utc)
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)
    else:
        n = n.astimezone(timezone.utc)
    today_start = n.replace(hour=0, minute=0, second=0, microsecond=0)
    days_since_sunday = (today_start.weekday() + 1) % 7
    this_week_sunday = today_start - timedelta(days=days_since_sunday)
    prev_week_start = this_week_sunday - timedelta(days=7)
    return prev_week_start, this_week_sunday
