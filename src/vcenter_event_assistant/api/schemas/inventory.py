"""影響範囲とインベントリ収集状態の応答。"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, field_validator

from vcenter_event_assistant.api.schemas.base import _normalize_to_utc

ImpactStatus = Literal[
    "unsupported_type",
    "not_recorded",
    "unknown_target",
    "absent_at_time",
    "stale",
    "ok",
]
ImpactRelation = Literal["cluster", "hosts", "vms", "datastores", "networks"]


class InventoryTarget(BaseModel):
    moid: str
    entity_type: str | None
    name: str


class InventoryImpactItem(InventoryTarget):
    removed: bool


class InventoryImpactGroup(BaseModel):
    relation: ImpactRelation
    items: list[InventoryImpactItem]
    total: int


class InventoryChange(BaseModel):
    kind: str
    other: InventoryTarget
    at: datetime
    action: Literal["opened", "closed"]


class InventoryChanges(BaseModel):
    items: list[InventoryChange]
    total: int


class InventoryImpactResponse(BaseModel):
    target: InventoryTarget
    at: datetime
    status: ImpactStatus
    recorded_since: datetime | None
    last_success_at: datetime | None
    observed_before: datetime | None
    observed_after: datetime | None
    groups: list[InventoryImpactGroup]
    changes: InventoryChanges | None = None


class InventoryVCenterStatus(BaseModel):
    vcenter_id: UUID
    vcenter_name: str
    is_enabled: bool
    first_success_at: datetime | None = None
    last_started_at: datetime | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_error: str | None = None
    last_warning: str | None = None
    last_warning_at: datetime | None = None
    object_count: int | None = None
    relation_count: int | None = None

    @field_validator(
        "first_success_at",
        "last_started_at",
        "last_success_at",
        "last_failure_at",
        "last_warning_at",
        mode="before",
    )
    @classmethod
    def datetimes_to_utc(cls, value: object) -> datetime | None:
        return None if value is None else _normalize_to_utc(value)


class InventoryStatusResponse(BaseModel):
    enabled: bool
    interval_seconds: int
    timeout_seconds: int
    vcenters: list[InventoryVCenterStatus]
