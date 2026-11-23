"""Alert rule and history API schemas."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from math import inf
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, UUID4, model_validator

from vcenter_event_assistant.services.event_patterns.definitions import BUILTIN_PATTERNS


AlertRuleType = Literal["event_score", "metric_threshold", "event_pattern"]


class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    rule_type: AlertRuleType
    is_enabled: bool = True
    alert_level: Literal["critical", "error", "warning"]
    config: dict = Field(default_factory=dict)


def ensure_alert_rule_config_json(config: dict) -> None:
    """DB に保存できる JSON に限る。NaN と Infinity は JSON の数値ではない。"""
    try:
        json.dumps(config, allow_nan=False)
    except ValueError as exc:
        raise ValueError("config numeric values must be finite") from exc


def validate_alert_rule_config(rule_type: str, cfg: dict) -> dict:
    """種類に応じて検証し、保存用の設定を返す。"""
    if rule_type == "metric_threshold":
        if "metric_key" not in cfg or not isinstance(cfg.get("metric_key"), str) or not cfg["metric_key"].strip():
            raise ValueError("metric_threshold config requires non-empty string metric_key")
        if "threshold" not in cfg or not isinstance(cfg.get("threshold"), (int, float)):
            raise ValueError("metric_threshold config requires numeric threshold")
    elif rule_type == "event_score":
        threshold_raw = cfg.get("threshold", cfg.get("min_notable_score", 60))
        if not isinstance(threshold_raw, (int, float)) or not 0 <= threshold_raw <= 100:
            raise ValueError("event_score config requires threshold (or min_notable_score) in 0..100")
        if "cooldown_minutes" in cfg and (
            not isinstance(cfg.get("cooldown_minutes"), (int, float))
            or not 1 <= cfg["cooldown_minutes"] < inf
        ):
            raise ValueError("event_score config.cooldown_minutes must be finite and >= 1 when set")
    elif rule_type == "event_pattern":
        pattern_ids = cfg.get("pattern_ids", [])
        if not isinstance(pattern_ids, list) or any(not isinstance(item, str) for item in pattern_ids):
            raise ValueError("event_pattern config.pattern_ids must be an array of strings")
        known = {pattern.id for pattern in BUILTIN_PATTERNS}
        unknown = sorted(set(pattern_ids) - known)
        if unknown:
            raise ValueError(f"unknown event_pattern pattern_ids: {', '.join(unknown)}")
        cooldown = cfg.get("cooldown_minutes", 10)
        if type(cooldown) is not int or cooldown < 1:
            raise ValueError("event_pattern config.cooldown_minutes must be an integer >= 1")
        if "pattern_ids" in cfg:
            return {**cfg, "pattern_ids": list(dict.fromkeys(pattern_ids))}
    return cfg


class AlertRuleUpdate(BaseModel):
    revision: UUID4
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
    revision: UUID4


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
    # その状態へ遷移した時刻。再送で進む notified_at と違い、後から変わらない。
    occurred_at: datetime
    # metric_threshold と event_pattern の context_key から取り出す。
    vcenter_id: uuid.UUID | None = None
    entity_moid: str | None = None
    # 解決できないときは None。
    entity_name: str | None = None
    channel: str
    success: bool | None
    error_message: str | None
    delivery_status: Literal["pending", "retrying", "succeeded", "failed", "skipped"]
    attempt_count: int | None = None
    last_attempt_at: datetime | None = None
    next_attempt_at: datetime | None = None
    can_resolve: bool = False

    @model_validator(mode="before")
    @classmethod
    def populate_rule_name(cls, v: object) -> object:
        if hasattr(v, "rule") and v.rule:
            v.rule_name = v.rule.name
        return v


class AlertStateResolveRequest(BaseModel):
    """イベントのアラートを手動で解消するリクエスト。"""

    rule_id: int
    context_key: str


class AlertHistoryListResponse(BaseModel):
    items: list[AlertHistoryRead]
    total: int
