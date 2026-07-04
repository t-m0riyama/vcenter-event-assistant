"""Event score rule API schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventScoreRuleCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=512)
    score_delta: int = Field(ge=-10_000, le=10_000)

    @field_validator("event_type", mode="before")
    @classmethod
    def strip_event_type(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


class EventScoreRuleUpdate(BaseModel):
    score_delta: int = Field(ge=-10_000, le=10_000)


class EventScoreRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    score_delta: int


class EventScoreRulesImportRequest(BaseModel):
    """一括インポート。``rules`` 内の ``event_type`` は重複不可。"""

    overwrite_existing: bool = True
    delete_rules_not_in_import: bool = False
    rules: list[EventScoreRuleCreate]


class EventScoreRulesImportResponse(BaseModel):
    """インポート適用後のルール件数と、再計算したイベント行数。"""

    rules_count: int
    events_updated: int
