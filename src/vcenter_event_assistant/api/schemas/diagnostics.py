"""診断設定 API の入出力。"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from vcenter_event_assistant.auth.timeutil import as_utc

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
