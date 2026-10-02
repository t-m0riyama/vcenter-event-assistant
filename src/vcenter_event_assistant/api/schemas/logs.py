"""Remote log search response models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from vcenter_event_assistant.api.schemas.base import _normalize_to_utc


class LogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    vcenter_id: UUID
    collector_id: str
    source_id: str
    host: str
    log_kind: str
    file_generation: str
    byte_offset: int
    occurred_at: datetime | None
    collected_at: datetime
    effective_at: datetime
    severity: str | None
    message: str

    @field_validator("occurred_at", "collected_at", "effective_at", mode="before")
    @classmethod
    def normalize_time(cls, value: object) -> datetime | None:
        return _normalize_to_utc(value) if value is not None else None


class LogListResponse(BaseModel):
    items: list[LogRead]
    total: int
