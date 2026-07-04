"""アラート評価の共通ユーティリティ。"""

from __future__ import annotations

from datetime import datetime, timezone


def as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
