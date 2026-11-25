"""インシデント記録の要求と応答。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from vcenter_event_assistant.api.schemas.base import UtcDateTime
from vcenter_event_assistant.api.schemas.diagnostics import DiagnosticRunRead
from vcenter_event_assistant.services.incidents import IncidentDetails, IncidentPage, IncidentStatus, LinkOutcome

IncidentLevel = Literal["critical", "error", "warning"]
EntryKind = Literal["note", "change", "link", "diagnostic"]
MAX_LINK_REQUEST = 100


def _title_must_have_text(value: str) -> str:
    if not value.strip():
        raise ValueError("title must not be blank")
    return value


IncidentTitle = Annotated[str, Field(min_length=1, max_length=200), AfterValidator(_title_must_have_text)]
IncidentAssignee = Annotated[str, Field(max_length=256)]
IncidentSummary = Annotated[str, Field(max_length=20_000)]


class IncidentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TimedSource(IncidentRequest):
    id: int
    occurred_at: UtcDateTime | None = None
    occurred_from: UtcDateTime | None = None
    occurred_to: UtcDateTime | None = None

    @model_validator(mode="after")
    def check_time(self) -> Self:
        if self.occurred_at is None and (self.occurred_from is None or self.occurred_to is None):
            raise ValueError("occurred_at or both occurred_from and occurred_to are required")
        return self

    def matches(self, occurred_at: datetime) -> bool:
        if self.occurred_at is not None:
            return occurred_at == self.occurred_at
        return (
            self.occurred_from is not None and self.occurred_to is not None
            and self.occurred_from <= occurred_at <= self.occurred_to
        )


class TimedLinksRequest(IncidentRequest):
    items: list[TimedSource] = Field(max_length=MAX_LINK_REQUEST)


class SnapshotLinksRequest(IncidentRequest):
    snapshot_ids: list[UUID] = Field(max_length=MAX_LINK_REQUEST)


class IncidentCreate(IncidentRequest):
    title: IncidentTitle
    status: IncidentStatus = "open"
    level: IncidentLevel | None = None
    assignee: IncidentAssignee | None = None
    summary: IncidentSummary = ""
    started_at: UtcDateTime | None = None
    events: list[TimedSource] = Field(default_factory=list, max_length=MAX_LINK_REQUEST)
    alerts: list[TimedSource] = Field(default_factory=list, max_length=MAX_LINK_REQUEST)
    snapshot_ids: list[UUID] = Field(default_factory=list, max_length=MAX_LINK_REQUEST)


class IncidentPatch(IncidentRequest):
    revision: UUID
    title: IncidentTitle | None = None
    status: IncidentStatus | None = None
    level: IncidentLevel | None = None
    assignee: IncidentAssignee | None = None
    summary: IncidentSummary | None = None
    started_at: UtcDateTime | None = None

    @field_validator("title")
    @classmethod
    def title_must_have_text(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("title must not be null")
        return value

    @field_validator("status")
    @classmethod
    def status_must_have_value(cls, value: IncidentStatus | None) -> IncidentStatus:
        if value is None:
            raise ValueError("status must not be null")
        return value


class EntryCreate(IncidentRequest):
    body: str = Field(max_length=4000)

    @field_validator("body")
    @classmethod
    def body_must_have_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("body must not be blank")
        return value


class IncidentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    status: IncidentStatus
    level: IncidentLevel | None
    assignee: str | None
    started_at: UtcDateTime | None
    resolved_at: UtcDateTime | None
    created_by: str
    updated_by: str
    created_at: UtcDateTime
    updated_at: UtcDateTime
    revision: UUID


class IncidentListItem(IncidentRead):
    event_count: int
    alert_count: int
    snapshot_count: int


class IncidentListResponse(BaseModel):
    items: list[IncidentListItem]
    total: int

    @classmethod
    def from_page(cls, page: IncidentPage) -> Self:
        return cls(
            items=[
                IncidentListItem(
                    **IncidentRead.model_validate(row.incident).model_dump(),
                    event_count=row.event_count,
                    alert_count=row.alert_count,
                    snapshot_count=row.snapshot_count,
                )
                for row in page.items
            ],
            total=page.total,
        )


class EntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    incident_id: UUID
    kind: EntryKind
    body: str
    author: str
    created_at: UtcDateTime
    deleted_by: str | None
    deleted_at: UtcDateTime | None


class EventLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    incident_id: UUID
    event_id: int
    vcenter_id: UUID
    collector_id: str
    vmware_key: int
    vcenter_name: str
    occurred_at: UtcDateTime
    event_type: str
    severity: str | None
    notable_score: int
    entity_type: str | None
    entity_name: str | None
    entity_moid: str | None
    user_name: str | None
    message: str
    user_comment: str | None
    added_by: str
    added_at: UtcDateTime
    source_exists: bool


class AlertLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    incident_id: UUID
    alert_history_id: int
    rule_id: int
    rule_name: str | None
    rule_type: str
    alert_level: str
    state: str
    context_key: str
    occurred_at: UtcDateTime
    vcenter_id: UUID | None
    vcenter_name: str | None
    entity_moid: str | None
    entity_name: str | None
    added_by: str
    added_at: UtcDateTime
    source_exists: bool


class SnapshotLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    snapshot_id: UUID
    operator_note: str
    snapshot_kind: str
    from_time: UtcDateTime
    to_time: UtcDateTime
    created_at: UtcDateTime
    has_result: bool


class IncidentDetail(IncidentRead):
    summary: str
    entries: list[EntryRead]
    diagnostic_runs: list[DiagnosticRunRead]
    events: list[EventLinkRead]
    alerts: list[AlertLinkRead]
    snapshots: list[SnapshotLinkRead]

    @classmethod
    def from_details(cls, details: IncidentDetails) -> Self:
        return cls(
            **IncidentRead.model_validate(details.incident).model_dump(),
            summary=details.incident.summary,
            entries=[EntryRead.model_validate(entry) for entry in details.entries],
            diagnostic_runs=[DiagnosticRunRead.model_validate(row) for row in details.diagnostic_runs],
            events=[
                EventLinkRead.model_validate({**vars(row), "source_exists": exists})
                for row, exists in details.events
            ],
            alerts=[
                AlertLinkRead.model_validate({**vars(row), "source_exists": exists})
                for row, exists in details.alerts
            ],
            snapshots=[
                SnapshotLinkRead(
                    id=link_id, snapshot_id=row.id, operator_note=row.operator_note, snapshot_kind=row.snapshot_kind,
                    from_time=row.from_time, to_time=row.to_time, created_at=row.created_at, has_result=has_result,
                )
                for link_id, row, has_result in details.snapshots
            ],
        )


class LinkResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | UUID
    result: LinkOutcome
    link_id: int | None = Field(default=None, exclude_if=lambda value: value is None)


class LinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    results: list[LinkResult]
    added: int


class CreateLinkResults(BaseModel):
    events: list[LinkResult]
    alerts: list[LinkResult]
    snapshots: list[LinkResult]


class IncidentCreateResponse(BaseModel):
    incident: IncidentDetail
    link_results: CreateLinkResults
