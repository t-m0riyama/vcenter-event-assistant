from __future__ import annotations

from datetime import datetime, timedelta, timezone

from vcenter_event_assistant.services.alert_eval_event_score_config import (
    EventScoreEvalConfig,
    event_eval_window_start,
    parse_event_score_rule_config,
)


def test_parse_event_score_rule_config_accepts_string_threshold() -> None:
    cfg = parse_event_score_rule_config({"threshold": "60", "cooldown_minutes": "5"})
    assert cfg == EventScoreEvalConfig(threshold=60, cooldown_minutes=5)


def test_parse_event_score_rule_config_rejects_invalid_threshold() -> None:
    assert parse_event_score_rule_config({"threshold": "high"}) is None


def test_parse_event_score_rule_config_defaults_cooldown() -> None:
    cfg = parse_event_score_rule_config({"threshold": 70})
    assert cfg == EventScoreEvalConfig(threshold=70, cooldown_minutes=10)


def test_parse_event_score_rule_config_legacy_min_notable_score() -> None:
    cfg = parse_event_score_rule_config({"min_notable_score": 55})
    assert cfg == EventScoreEvalConfig(threshold=55, cooldown_minutes=10)


def test_event_eval_window_start_subtracts_hours() -> None:
    now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    start = event_eval_window_start(now=now, lookback_hours=6)
    assert start == now - timedelta(hours=6)
