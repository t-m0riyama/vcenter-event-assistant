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


class EventRead(BaseModel):
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


class MetricPoint(BaseModel):
    sampled_at: datetime
    value: float
    entity_name: str
    entity_moid: str
    metric_key: str
    vcenter_id: uuid.UUID


class MetricSeriesResponse(BaseModel):
    """Paginated metric samples: ``total`` matches filters before ``limit``; ``points`` is capped."""

    points: list[MetricPoint]
    total: int


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


class DashboardSummary(BaseModel):
    vcenter_count: int
    events_last_24h: int
    notable_events_last_24h: int
    top_notable_events: list[EventRead]
    high_cpu_hosts: list[HighCpuHostRow]
