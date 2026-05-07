"""チャット用インシデント統合タイムラインの整形。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field

IncidentTimelineKind = Literal["alert", "event", "metric"]

_KIND_PRIORITY: dict[IncidentTimelineKind, int] = {
    "alert": 0,
    "event": 1,
    "metric": 2,
}


def _as_utc(dt: datetime) -> datetime:
    """naive の場合は UTC とみなし、aware は UTC に正規化する。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_entry_timestamp(entry: IncidentTimelineEntry) -> IncidentTimelineEntry:
    """entry.timestamp_utc を UTC 正規化したコピーを返す。"""
    normalized_ts = _as_utc(entry.timestamp_utc)
    return IncidentTimelineEntry(
        timestamp_utc=normalized_ts,
        kind=entry.kind,
        title=entry.title,
    )


class IncidentTimelineEntry(BaseModel):
    """タイムライン 1 要素（種別・時刻・表示名）。"""

    timestamp_utc: datetime
    kind: IncidentTimelineKind
    title: str = Field(min_length=1)


class IncidentTimelineColumn(BaseModel):
    """同一時刻に属する可視要素と省略件数。"""

    timestamp_utc: datetime
    bucket_start_utc: datetime | None = None
    bucket_end_utc: datetime | None = None
    items: list[IncidentTimelineEntry] = Field(default_factory=list)
    visible_items: list[IncidentTimelineEntry]
    hidden_count: int = Field(ge=0)


class IncidentTimelinePayload(BaseModel):
    """時刻列の配列。時刻は新しい順。"""

    columns: list[IncidentTimelineColumn]


def build_chat_incident_timeline(
    entries: list[IncidentTimelineEntry],
    *,
    max_visible_items_per_timestamp: int = 10,
    bucket_seconds: int | None = None,
) -> IncidentTimelinePayload:
    """同時刻を種別順で整形し、上位表示数と hidden_count を付与する。"""
    if max_visible_items_per_timestamp < 1:
        raise ValueError("max_visible_items_per_timestamp must be >= 1")
    if bucket_seconds is not None and bucket_seconds < 1:
        raise ValueError("bucket_seconds must be >= 1 when provided")

    grouped: dict[datetime, list[tuple[int, IncidentTimelineEntry]]] = defaultdict(list)
    for idx, entry in enumerate(entries):
        grouped[_as_utc(entry.timestamp_utc)].append((idx, entry))

    columns: list[IncidentTimelineColumn] = []
    for timestamp_utc in sorted(grouped.keys(), reverse=True):
        items = grouped[timestamp_utc]
        ordered = sorted(
            items,
            key=lambda item: (_KIND_PRIORITY[item[1].kind], item[0]),
        )
        ordered_entries = [_normalize_entry_timestamp(item[1]) for item in ordered]
        visible_items = ordered_entries[:max_visible_items_per_timestamp]
        hidden_count = max(0, len(ordered_entries) - len(visible_items))
        bucket_start_utc = timestamp_utc if bucket_seconds is not None else None
        bucket_end_utc = (
            timestamp_utc + timedelta(seconds=bucket_seconds)
            if bucket_seconds is not None
            else None
        )
        columns.append(
            IncidentTimelineColumn(
                timestamp_utc=timestamp_utc,
                bucket_start_utc=bucket_start_utc,
                bucket_end_utc=bucket_end_utc,
                items=ordered_entries,
                visible_items=visible_items,
                hidden_count=hidden_count,
            ),
        )

    return IncidentTimelinePayload(columns=columns)
