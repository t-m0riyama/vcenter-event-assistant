"""Alert rule and history API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    rule_type: Literal["event_score", "metric_threshold"]
    is_enabled: bool = True
    alert_level: Literal["critical", "error", "warning"]
    config: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_config_for_rule_type(self) -> AlertRuleCreate:
        cfg = self.config
        if not isinstance(cfg, dict):
            raise ValueError("config must be an object")
        if self.rule_type == "metric_threshold":
            if "metric_key" not in cfg or not isinstance(cfg.get("metric_key"), str) or not cfg["metric_key"].strip():
                raise ValueError("metric_threshold config requires non-empty string metric_key")
            if "threshold" not in cfg or not isinstance(cfg.get("threshold"), (int, float)):
                raise ValueError("metric_threshold config requires numeric threshold")
        elif self.rule_type == "event_score":
            if "min_score" in cfg and not isinstance(cfg.get("min_score"), (int, float)):
                raise ValueError("event_score config.min_score must be numeric when set")
            if "event_type" in cfg and not isinstance(cfg.get("event_type"), str):
                raise ValueError("event_score config.event_type must be a string when set")
        return self


class AlertRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_enabled: bool | None = None
    alert_level: Literal["critical", "error", "warning"] | None = None
    config: dict | None = None


class AlertRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    rule_type: str
    is_enabled: bool
    alert_level: Literal["critical", "error", "warning"]
    config: dict
    created_at: datetime


class AlertRulesImportRequest(BaseModel):
    """一括インポート。``rules`` 内の ``name`` は重複不可。"""

    overwrite_existing: bool = True
    delete_rules_not_in_import: bool = False
    rules: list[AlertRuleCreate]


class AlertRulesImportResponse(BaseModel):
    """インポート適用後のアラートルール件数。"""

    rules_count: int


class AlertHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_id: int
    rule_name: str | None = None
    rule_type: str = ""
    alert_level: Literal["critical", "error", "warning"]
    state: str
    context_key: str
    notified_at: datetime
    channel: str
    success: bool | None
    error_message: str | None
    can_resolve: bool = False

    @model_validator(mode="before")
    @classmethod
    def populate_rule_name(cls, v: object) -> object:
        if hasattr(v, "rule") and v.rule:
            v.rule_name = v.rule.name
        return v


class AlertStateResolveRequest(BaseModel):
    """イベントスコア型アラートの手動解消リクエスト。"""

    rule_id: int
    context_key: str


class AlertHistoryListResponse(BaseModel):
    items: list[AlertHistoryRead]
    total: int
