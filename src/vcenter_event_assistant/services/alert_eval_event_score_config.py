"""event_score アラート評価用の純関数（DB 非依存）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class EventScoreEvalConfig:
    threshold: int
    cooldown_minutes: int


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def parse_event_score_rule_config(raw: dict[str, Any]) -> EventScoreEvalConfig | None:
    """ルール config から threshold / cooldown を正規化。失敗時は None。"""
    legacy = raw.get("min_notable_score")
    threshold_raw = raw.get("threshold", legacy if legacy is not None else 60)
    threshold = _coerce_int(threshold_raw)
    if threshold is None or not 0 <= threshold <= 100:
        return None
    cooldown = _coerce_int(raw.get("cooldown_minutes"))
    if cooldown is None:
        cooldown = 10
    if cooldown < 1:
        return None
    return EventScoreEvalConfig(threshold=threshold, cooldown_minutes=cooldown)


def event_eval_window_start(*, now: datetime, lookback_hours: int) -> datetime:
    """評価対象イベントの occurred_at 下限（UTC 想定）。"""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now - timedelta(hours=lookback_hours)
