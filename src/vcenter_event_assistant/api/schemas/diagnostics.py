"""診断設定 API の入出力。"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from vcenter_event_assistant.auth.timeutil import as_utc
from vcenter_event_assistant.services.diagnostics.catalog import BUILTIN_COMMANDS
from vcenter_event_assistant.services.diagnostics.procedures import BUILTIN_PROCEDURES
from vcenter_event_assistant.services.event_patterns.definitions import EventPattern

Product = Literal["esxi", "vcenter"]


class RevisionInput(BaseModel):
    revision: UUID


class TargetInput(BaseModel):
    product: Product
    vcenter_id: UUID
    host_moid: str | None = Field(default=None, min_length=1, max_length=256)
    host_name: str = Field(min_length=1, max_length=512)
    ssh_connection_id: UUID


class TargetUpdate(TargetInput, RevisionInput):
    pass


class ParameterDefinition(BaseModel):
    name: str
    type: str


class CommandInput(BaseModel):
    product: Product
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(max_length=1000)
    template: str = Field(min_length=1, max_length=1000)
    param_definitions: list[ParameterDefinition] = Field(default_factory=list)


class CommandUpdate(CommandInput, RevisionInput):
    pass


class SettingRead(RevisionInput):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_by: str
    updated_by: str
    created_at: Annotated[datetime, AfterValidator(as_utc)]
    updated_at: Annotated[datetime, AfterValidator(as_utc)]


class TargetRead(TargetInput, SettingRead):
    pass


class CommandRead(CommandInput, SettingRead):
    pass


class BuiltinCommandRead(CommandInput):
    id: str


class CommandCatalog(BaseModel):
    builtin: list[BuiltinCommandRead]
    custom: list[CommandRead]
    parameter_types: tuple[str, ...]


class BuiltinCommandRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    builtin: str


class CustomCommandRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    custom: UUID


class DiagnosticPreviewInput(BaseModel):
    target_id: UUID
    command: BuiltinCommandRef | CustomCommandRef
    params: dict[str, str]


class DiagnosticRunInput(DiagnosticPreviewInput):
    fingerprint: str


class DiagnosticPreview(BaseModel):
    command_line: str
    host_name: str
    ssh_host: str
    ssh_port: int
    ssh_username: str
    fingerprint: str


class DiagnosticRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    incident_id: UUID
    command_kind: Literal["builtin", "custom"]
    command_ref: str
    command_title: str
    command_line: str
    executed: bool | None
    params: dict[str, str]
    target_id: UUID | None
    product: Product
    host_name: str
    ssh_host: str
    ssh_port: int
    ssh_username: str
    status: Literal["succeeded", "failed", "error"]
    exit_status: int | None
    error_code: str | None
    stdout_truncated: bool
    stderr_truncated: bool
    elapsed_ms: int
    started_at: Annotated[datetime, AfterValidator(as_utc)]
    finished_at: Annotated[datetime, AfterValidator(as_utc)]
    run_by: str


class DiagnosticRunOutput(DiagnosticRunRead):
    stdout: str
    stderr: str


class ProcedureCommandRead(BaseModel):
    id: str
    title: str


class ProcedureStepRead(BaseModel):
    text: str
    commands: list[ProcedureCommandRead]


class ProcedureRead(BaseModel):
    pattern_id: str
    title: str
    steps: list[ProcedureStepRead]

    @classmethod
    def from_pattern(cls, pattern: EventPattern) -> "ProcedureRead":
        return cls(
            pattern_id=pattern.id,
            title=pattern.title,
            steps=[
                ProcedureStepRead(
                    text=step.text,
                    commands=[
                        ProcedureCommandRead(id=command_id, title=BUILTIN_COMMANDS[command_id].title)
                        for command_id in step.command_ids
                    ],
                )
                for step in BUILTIN_PROCEDURES[pattern.id]
            ],
        )


class ProcedureReasonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: Literal["alert", "event"]
    link_id: int


class ProcedureTargetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    host_name: str


class ProcedureCandidateRead(BaseModel):
    procedure: ProcedureRead
    reasons: list[ProcedureReasonRead]
    target: ProcedureTargetRead | None
