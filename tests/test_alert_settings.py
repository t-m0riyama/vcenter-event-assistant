from vcenter_event_assistant.settings import Settings

def test_alert_settings_default():
    # VEA_PYTEST=1 が conftest で設定されているため、.env は読まれない
    settings = Settings()
    assert settings.smtp_port == 587
    assert settings.smtp_host is None
    assert settings.alert_eval_interval_seconds == 60
    assert settings.alert_email_from == "noreply@example.com"

def test_alert_settings_env_override(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test.com")
    monkeypatch.setenv("SMTP_PORT", "25")
    monkeypatch.setenv("ALERT_EVAL_INTERVAL_SECONDS", "30")
    
    settings = Settings()
    assert settings.smtp_host == "smtp.test.com"
    assert settings.smtp_port == 25
    assert settings.alert_eval_interval_seconds == 30

def test_alert_settings_empty_str_normalization(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "  ")
    monkeypatch.setenv("ALERT_EMAIL_TO", "")
    
    settings = Settings()
    assert settings.smtp_host is None
    assert settings.alert_email_to is None
