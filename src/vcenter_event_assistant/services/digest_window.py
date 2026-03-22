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
