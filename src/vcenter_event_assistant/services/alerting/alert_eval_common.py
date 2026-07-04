"""アラート評価の共通ユーティリティ。"""

from __future__ import annotations

from datetime import datetime, timezone


def as_utc(dt: datetime) -> datetime:
    """naive datetime を UTC aware に正規化する。

    Args:
        dt: タイムゾーン付きまたは naive の日時。

    Returns:
        UTC ``tzinfo`` 付き日時。
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
