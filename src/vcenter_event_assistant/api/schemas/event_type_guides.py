"""Event type guide API schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
