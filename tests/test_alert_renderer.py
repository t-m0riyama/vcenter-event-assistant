from vcenter_event_assistant.services.notification.renderer import NotificationRenderer
from vcenter_event_assistant.db.models import AlertRule, AlertState
from datetime import datetime, timezone

def test_render_firing_alert():
    renderer = NotificationRenderer()
    rule = AlertRule(name="High CPU", rule_type="metric_threshold")
    state = AlertState(
        state="firing",
        context_key="host-123",
        fired_at=datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)
    )
    # config 等のコンテキストデータ
    context = {
        "rule_name": rule.name,
        "state": state.state,
        "context_key": state.context_key,
        "fired_at": state.fired_at,
        "details": "Usage is 95%"
    }
    
    subject, body = renderer.render(rule, state, context)
    
    assert "[FIRING]" in subject
    assert "High CPU" in subject
    assert "High CPU" in body
    assert "FIRING" in body.upper()
    assert "host-123" in body
    assert "95%" in body

def test_render_resolved_alert():
    renderer = NotificationRenderer()
    rule = AlertRule(name="High CPU", rule_type="metric_threshold")
    state = AlertState(
        state="resolved",
        context_key="host-123",
        fired_at=datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc),
        resolved_at=datetime(2026, 4, 23, 11, 0, 0, tzinfo=timezone.utc)
    )
    context = {
        "rule_name": rule.name,
        "state": state.state,
        "context_key": state.context_key,
        "fired_at": state.fired_at,
        "resolved_at": state.resolved_at,
        "details": "Usage is now 20%"
    }
    
    subject, body = renderer.render(rule, state, context)
    
    assert "[RESOLVED]" in subject
    assert "High CPU" in subject
    assert "RESOLVED" in body.upper()
    assert "Usage is now 20%" in body
