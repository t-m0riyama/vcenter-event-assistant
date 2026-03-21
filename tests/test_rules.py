"""Notable scoring rules."""

from vcenter_event_assistant.rules.notable import flag_metric_spike, score_event


def test_score_event_severity() -> None:
    r = score_event(event_type="UserLoginSessionEvent", severity="warning", message="x")
    assert r.score >= 20


def test_score_event_high_risk_type() -> None:
    r = score_event(event_type="VmFailedToPowerOnEvent", severity="info", message="failed")
    assert "high_risk_type" in r.tags


def test_flag_metric_spike() -> None:
    r = flag_metric_spike(metric_key="host.cpu.usage_pct", value=96.0)
    assert r.score >= 80
