"""Metric time series API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator

from vcenter_event_assistant.api.schemas.base import _normalize_to_utc


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
        return _normalize_to_utc(v)


class MetricSeriesResponse(BaseModel):
    """Paginated metric samples: ``total`` matches filters before ``limit``; ``points`` is capped."""

    points: list[MetricPoint]
    total: int


class MetricKeysResponse(BaseModel):
    """Distinct ``metric_key`` values present in stored samples (optionally scoped to one vCenter)."""

    metric_keys: list[str]
