"""event_score アラート評価用の純関数（DB 非依存）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class EventScoreEvalConfig:
    """``event_score`` ルール評価に必要な閾値とクールダウン。"""

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


def merge_latest_qualifying_by_event_type(
    rows: list[tuple[str, datetime]],
) -> dict[str, datetime]:
    """イベント種別ごとに qualifying 行の最大 occurred_at を保持して集約する。"""
    out: dict[str, datetime] = {}
    for event_type, occurred_at in rows:
        prev = out.get(event_type)
        if prev is None or occurred_at > prev:
            out[event_type] = occurred_at
    return out


def event_score_should_notify(
    *,
    current_state: Literal["firing", "resolved"] | None,
    last_notified_at: datetime | None,
    last_qualifying_at: datetime,
    last_fired_qualifying_at: datetime | None,
    now: datetime,
    cooldown_minutes: int,
) -> bool:
    """イベントスコアアラートの再通知許可判定（クールダウン）。

    Args:
        current_state: 現在のアラート状態。未評価（None）または resolved 後は最初の検知として通知許可。
        last_notified_at: 直近通知時刻。
        last_qualifying_at: 集約済み qualifying の最新発生時刻。
        last_fired_qualifying_at: 直近通知時点の qualifying 発生時刻（firing 中の fired_at）。
        now: 判定基準時刻。
        cooldown_minutes: firing 連続時の再通知までの最短間隔。

    Returns:
        通知すべきとき True。
    """
    if current_state is None or current_state == "resolved":
        return True
    if last_notified_at is None:
        return True
    if last_fired_qualifying_at is not None and last_qualifying_at <= last_fired_qualifying_at:
        return False
    if now - last_notified_at >= timedelta(minutes=cooldown_minutes):
        return True
    return False
