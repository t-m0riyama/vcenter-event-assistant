"""Dashboard summary API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from vcenter_event_assistant.api.schemas.base import _normalize_to_utc
from vcenter_event_assistant.api.schemas.events import EventRead, EventTypeGuideSnippet


class HighCpuHostRow(BaseModel):
    """Dashboard summary row: ``sampled_at`` is normalized to UTC so JSON uses ``Z`` (JS parses as UTC)."""

    vcenter_id: str
    vcenter_label: str = Field(
        description=(
            "表示用（登録時の表示名 VCenter.name。空のときは vcenter_id 短縮。接続 host は使わない）"
        )
    )
    entity_name: str
    entity_moid: str
    value: float
    sampled_at: datetime

    @field_validator("sampled_at", mode="before")
    @classmethod
    def sampled_at_to_utc(cls, v: object) -> datetime:
        return _normalize_to_utc(v)


class HighMemHostRow(BaseModel):
    """Dashboard summary row for peak host memory usage (same shape as CPU row; separate schema type)."""

    vcenter_id: str
    vcenter_label: str = Field(
        description=(
            "表示用（登録時の表示名 VCenter.name。空のときは vcenter_id 短縮。接続 host は使わない）"
        )
    )
    entity_name: str
    entity_moid: str
    value: float
    sampled_at: datetime

    @field_validator("sampled_at", mode="before")
    @classmethod
    def sampled_at_to_utc(cls, v: object) -> datetime:
        return _normalize_to_utc(v)


class EventTypeCountRow(BaseModel):
    """Event type bucket: ``event_count`` is occurrences in the dashboard window (e.g. last 24h)."""

    event_type: str
    event_count: int
    max_notable_score: int
    type_guide: EventTypeGuideSnippet | None = None


class DashboardSummary(BaseModel):
    vcenter_count: int
    events_last_24h: int
    notable_events_last_24h: int
    top_notable_events: list[EventRead]
    high_cpu_hosts: list[HighCpuHostRow]
    high_mem_hosts: list[HighMemHostRow]
    top_event_types_24h: list[EventTypeCountRow]
