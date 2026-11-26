"""インベントリの影響範囲・構成の差分・収集状態の応答。"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, JsonValue, field_validator

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


class IncidentTimelineConfigDiff(BaseModel):
    id: int
    category: str
    category_label: str
    element: str | None
    element_label: str | None
    attribute: str | None
    attribute_label: str | None
    old_value: JsonValue
    new_value: JsonValue
    truncated: bool
    changed_after: datetime
    observed_at: datetime


class InventoryConfigDiffResponse(BaseModel):
    target: InventoryTarget
    status: Literal["disabled", "not_recorded", "ok"]
    recorded_since: datetime | None
    last_success_at: datetime | None
    items: list[IncidentTimelineConfigDiff]
    total: int


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
    config_first_success_at: datetime | None = None
    config_last_started_at: datetime | None = None
    config_last_success_at: datetime | None = None
    config_last_failure_at: datetime | None = None
    config_last_error: str | None = None
    config_last_warning: str | None = None
    config_last_warning_at: datetime | None = None
    config_object_count: int | None = None
    config_deferred_count: int | None = None

    @field_validator(
        "first_success_at",
        "last_started_at",
        "last_success_at",
        "last_failure_at",
        "last_warning_at",
        "config_first_success_at",
        "config_last_started_at",
        "config_last_success_at",
        "config_last_failure_at",
        "config_last_warning_at",
        mode="before",
    )
    @classmethod
    def datetimes_to_utc(cls, value: object) -> datetime | None:
        return None if value is None else _normalize_to_utc(value)


class InventoryStatusResponse(BaseModel):
    enabled: bool
    config_enabled: bool
    interval_seconds: int
    timeout_seconds: int
    vcenters: list[InventoryVCenterStatus]
