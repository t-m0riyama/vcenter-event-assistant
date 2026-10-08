"""Notable scoring rules."""

from vcenter_event_assistant.rules.notable import (
    clamp_notable_total,
    final_notable_score,
    flag_metric_spike,
    score_event,
)


def test_score_event_severity() -> None:
    r = score_event(event_type="UserLoginSessionEvent", severity="warning", message="x")
    assert r.score >= 20


def test_score_event_high_risk_type() -> None:
    r = score_event(event_type="VmFailedToPowerOnEvent", severity="info", message="failed")
    assert "high_risk_type" in r.tags


def test_flag_metric_spike() -> None:
    r = flag_metric_spike(metric_key="host.cpu.usage_pct", value=96.0)
    assert r.score >= 80


def test_clamp_notable_total() -> None:
    assert clamp_notable_total(50, 10) == 60
    assert clamp_notable_total(95, 20) == 100
    assert clamp_notable_total(10, -30) == 0
    assert clamp_notable_total(0, -5) == 0


def test_final_notable_score_additive() -> None:
    base = score_event(event_type="UserLoginSessionEvent", severity="info", message="x").score
    delta = 12
    assert final_notable_score(
        event_type="UserLoginSessionEvent",
        severity="info",
        message="x",
        score_delta=delta,
    ) == clamp_notable_total(base, delta)
