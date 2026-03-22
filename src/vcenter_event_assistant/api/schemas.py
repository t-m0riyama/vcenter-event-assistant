"""Pydantic schemas for API."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VCenterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    host: str = Field(min_length=1, max_length=512)
    port: int = Field(default=443, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=1, max_length=2048)
    is_enabled: bool = True


class VCenterUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    host: str | None = Field(default=None, min_length=1, max_length=512)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, min_length=1, max_length=512)
    password: str | None = Field(default=None, min_length=1, max_length=2048)
    is_enabled: bool | None = None


class VCenterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    host: str
    port: int
    username: str
    is_enabled: bool
    created_at: datetime


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
        if not isinstance(v, datetime):
            raise TypeError("occurred_at must be a datetime")
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


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


class MetricPoint(BaseModel):
    """Metric sample: ``sampled_at`` is normalized to UTC so JSON uses ``Z`` (JS parses as UTC)."""

    sampled_at: datetime
    value: float
    entity_name: str
    entity_moid: str
    metric_key: str
    vcenter_id: uuid.UUID

    @field_validator("sampled_at", mode="before")
    @classmethod
    def sampled_at_to_utc(cls, v: object) -> datetime:
        if not isinstance(v, datetime):
            raise TypeError("sampled_at must be a datetime")
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class MetricSeriesResponse(BaseModel):
    """Paginated metric samples: ``total`` matches filters before ``limit``; ``points`` is capped."""

    points: list[MetricPoint]
    total: int


class MetricKeysResponse(BaseModel):
    """Distinct ``metric_key`` values present in stored samples (optionally scoped to one vCenter)."""

    metric_keys: list[str]


class HighCpuHostRow(BaseModel):
    """Dashboard summary row: ``sampled_at`` is normalized to UTC so JSON uses ``Z`` (JS parses as UTC)."""

    vcenter_id: str
    entity_name: str
    entity_moid: str
    value: float
    sampled_at: datetime

    @field_validator("sampled_at", mode="before")
    @classmethod
    def sampled_at_to_utc(cls, v: object) -> datetime:
        if not isinstance(v, datetime):
            raise TypeError("sampled_at must be a datetime")
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class HighMemHostRow(BaseModel):
    """Dashboard summary row for peak host memory usage (same shape as CPU row; separate schema type)."""

    vcenter_id: str
    entity_name: str
    entity_moid: str
    value: float
    sampled_at: datetime

    @field_validator("sampled_at", mode="before")
    @classmethod
    def sampled_at_to_utc(cls, v: object) -> datetime:
        if not isinstance(v, datetime):
            raise TypeError("sampled_at must be a datetime")
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


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


class AppConfigResponse(BaseModel):
    """Read-only retention settings (from environment)."""

    event_retention_days: int
    metric_retention_days: int
    perf_sample_interval_seconds: int


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


class EventScoreRuleCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=512)
    score_delta: int = Field(ge=-10_000, le=10_000)

    @field_validator("event_type", mode="before")
    @classmethod
    def strip_event_type(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


class EventScoreRuleUpdate(BaseModel):
    score_delta: int = Field(ge=-10_000, le=10_000)


class EventScoreRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    score_delta: int


_GUIDE_TEXT_MAX = 8000


class EventTypeGuideCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=512)
    general_meaning: str | None = Field(default=None, max_length=_GUIDE_TEXT_MAX)
    typical_causes: str | None = Field(default=None, max_length=_GUIDE_TEXT_MAX)
    remediation: str | None = Field(default=None, max_length=_GUIDE_TEXT_MAX)
    action_required: bool = False

    @field_validator("event_type", mode="before")
    @classmethod
    def strip_event_type(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("general_meaning", "typical_causes", "remediation", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: object) -> object:
        if v == "":
            return None
        return v


class EventTypeGuideUpdate(BaseModel):
    general_meaning: str | None = Field(default=None, max_length=_GUIDE_TEXT_MAX)
    typical_causes: str | None = Field(default=None, max_length=_GUIDE_TEXT_MAX)
    remediation: str | None = Field(default=None, max_length=_GUIDE_TEXT_MAX)
    action_required: bool | None = None

    @field_validator("general_meaning", "typical_causes", "remediation", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: object) -> object:
        if v == "":
            return None
        return v


class EventTypeGuideRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    general_meaning: str | None
    typical_causes: str | None
    remediation: str | None
    action_required: bool


class EventTypeGuidesImportRequest(BaseModel):
    """一括インポート。``guides`` 内の ``event_type`` は重複不可。"""

    overwrite_existing: bool = True
    delete_guides_not_in_import: bool = False
    guides: list[EventTypeGuideCreate]


class EventTypeGuidesImportResponse(BaseModel):
    """インポート適用後のガイド件数。"""

    guides_count: int


class EventScoreRulesImportRequest(BaseModel):
    """一括インポート。``rules`` 内の ``event_type`` は重複不可。"""

    overwrite_existing: bool = True
    delete_rules_not_in_import: bool = False
    rules: list[EventScoreRuleCreate]


class EventScoreRulesImportResponse(BaseModel):
    """インポート適用後のルール件数と、再計算したイベント行数。"""

    rules_count: int
    events_updated: int
