from __future__ import annotations

from datetime import datetime, timedelta, timezone

from vcenter_event_assistant.services.alert_eval_event_score_config import (
    EventScoreEvalConfig,
    event_eval_window_start,
    event_score_should_notify,
    merge_latest_qualifying_by_event_type,
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


def test_merge_latest_qualifying_by_event_type_keeps_max_occurred_at() -> None:
    base = datetime(2026, 5, 23, 10, 0, tzinfo=timezone.utc)
    rows = [
        ("vim.event.A", base),
        ("vim.event.A", base + timedelta(minutes=2)),
        ("vim.event.B", base + timedelta(minutes=1)),
    ]
    merged = merge_latest_qualifying_by_event_type(rows)
    assert merged == {
        "vim.event.A": base + timedelta(minutes=2),
        "vim.event.B": base + timedelta(minutes=1),
    }


def test_event_score_should_notify_initial_firing() -> None:
    now = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)
    assert event_score_should_notify(
        current_state=None,
        last_notified_at=None,
        last_qualifying_at=now - timedelta(minutes=1),
        last_fired_qualifying_at=None,
        now=now,
        cooldown_minutes=10,
    )


def test_event_score_should_notify_false_within_cooldown() -> None:
    now = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)
    last_notified = now - timedelta(minutes=3)
    assert not event_score_should_notify(
        current_state="firing",
        last_notified_at=last_notified,
        last_qualifying_at=now,
        last_fired_qualifying_at=now - timedelta(minutes=10),
        now=now,
        cooldown_minutes=10,
    )


def test_event_score_should_notify_true_after_cooldown_with_new_qualifying() -> None:
    now = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)
    last_notified = now - timedelta(minutes=11)
    assert event_score_should_notify(
        current_state="firing",
        last_notified_at=last_notified,
        last_qualifying_at=now,
        last_fired_qualifying_at=now - timedelta(minutes=20),
        now=now,
        cooldown_minutes=10,
    )


def test_event_score_should_notify_false_after_cooldown_without_new_qualifying() -> None:
    now = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)
    qualifying = now - timedelta(minutes=20)
    assert not event_score_should_notify(
        current_state="firing",
        last_notified_at=now - timedelta(minutes=11),
        last_qualifying_at=qualifying,
        last_fired_qualifying_at=qualifying,
        now=now,
        cooldown_minutes=10,
    )


def test_event_score_should_notify_after_resolved() -> None:
    now = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)
    assert event_score_should_notify(
        current_state="resolved",
        last_notified_at=now - timedelta(hours=1),
        last_qualifying_at=now,
        last_fired_qualifying_at=now - timedelta(hours=2),
        now=now,
        cooldown_minutes=10,
    )
