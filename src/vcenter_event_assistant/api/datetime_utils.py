"""Datetime helpers for API query parameters."""

from __future__ import annotations

from datetime import datetime, timezone


def to_utc(dt: datetime) -> datetime:
    """
    Normalize query datetimes for comparisons against ``DateTime(timezone=True)`` columns.

    Naive values are treated as UTC (matching :func:`event_rate_series`). Offset-aware values
    are converted to UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
