"""Event list and rate-series API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from vcenter_event_assistant.api.schemas.base import _normalize_to_utc


class EventTypeGuideSnippet(BaseModel):
    """イベント種別に紐づくガイド（一覧 API で付与）。"""

    general_meaning: str | None = None
    typical_causes: str | None = None
    remediation: str | None = None
    action_required: bool = False


class EventRead(BaseModel):
    """Event row: ``occurred_at`` is normalized to UTC so JSON uses ``Z`` (JS parses as UTC)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    vcenter_id: uuid.UUID
    occurred_at: datetime
    event_type: str
    message: str
    severity: str | None
    user_name: str | None
    entity_name: str | None
    entity_type: str | None
    notable_score: int
    notable_tags: list | None
    user_comment: str | None = None
    type_guide: EventTypeGuideSnippet | None = None

    @field_validator("occurred_at", mode="before")
    @classmethod
    def occurred_at_to_utc(cls, v: object) -> datetime:
        return _normalize_to_utc(v)


class EventUserCommentPatch(BaseModel):
    """Update operator memo on a single event (``null`` clears the comment)."""

    user_comment: str | None = Field(..., max_length=8000)

    @field_validator("user_comment", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: object) -> object:
        if v == "":
            return None
        return v


class EventListResponse(BaseModel):
    """Event list page: ``total`` matches filters before ``limit``/``offset``; ``items`` is the current page."""

    items: list[EventRead]
    total: int


class EventRateBucket(BaseModel):
    """UTC bucket start and event count in ``[bucket_start, bucket_start + bucket_seconds)``."""

    bucket_start: datetime
    count: int


class EventRateSeriesResponse(BaseModel):
    """Histogram of event counts per time bucket (aligned to UTC epoch boundaries)."""

    bucket_seconds: int
    buckets: list[EventRateBucket]


class EventTypesResponse(BaseModel):
    """Distinct event types for UI pickers."""

    event_types: list[str]
