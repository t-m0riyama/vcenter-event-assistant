"""Read-only collector plugin status API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

from vcenter_event_assistant.api.schemas.base import _normalize_to_utc


class CollectorRunStatusRead(BaseModel):
    """Latest execution status for one collector and vCenter."""

    vcenter_id: uuid.UUID
    vcenter_name: str
    status: Literal["idle", "running", "ok", "failed"]
    collector_version: str
    last_started_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    events_inserted: int
    metrics_inserted: int
    error: str | None

    @field_validator(
        "last_started_at", "last_success_at", "last_failure_at", mode="before"
    )
    @classmethod
    def datetimes_to_utc(cls, value: object) -> datetime | None:
        if value is None:
            return None
        return _normalize_to_utc(value)


class CollectorStatusRead(BaseModel):
    """Installed, configured, or failed collector registration."""

    id: str
    display_name: str | None
    source: str
    status: Literal["enabled", "disabled", "failed"]
    error: str | None
    version: str | None
    api_version: int | None
    data_kinds: list[Literal["event", "metric"]]
    interval_seconds: int | None
    timeout_seconds: float | None
    runs: list[CollectorRunStatusRead]


class CollectorStatusListResponse(BaseModel):
    generation: int
    collectors: list[CollectorStatusRead]
