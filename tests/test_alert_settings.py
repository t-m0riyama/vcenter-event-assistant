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

def test_alert_snapshot_lookback_hours_default():
    settings = Settings()
    assert settings.alert_snapshot_lookback_hours == 2


def test_alert_snapshot_lookback_hours_env_override(monkeypatch):
    monkeypatch.setenv("ALERT_SNAPSHOT_LOOKBACK_HOURS", "4")
    settings = Settings()
    assert settings.alert_snapshot_lookback_hours == 4


def test_alert_event_eval_lookback_hours_default():
    settings = Settings()
    assert settings.alert_event_eval_lookback_hours == 1


def test_alert_event_eval_lookback_hours_env_override(monkeypatch):
    monkeypatch.setenv("ALERT_EVENT_EVAL_LOOKBACK_HOURS", "6")
    settings = Settings()
    assert settings.alert_event_eval_lookback_hours == 6


def test_alert_settings_empty_str_normalization(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "  ")
    monkeypatch.setenv("ALERT_EMAIL_TO", "")
    
    settings = Settings()
    assert settings.smtp_host is None
    assert settings.alert_email_to is None


def test_delivery_settings_defaults():
    settings = Settings()
    assert settings.alert_delivery_interval_seconds == 10
    assert settings.alert_delivery_batch_size == 20
    assert settings.alert_retry_initial_seconds == 60
    assert settings.alert_retry_max_seconds == 3600
    assert settings.alert_retry_ttl_seconds == 86400


def test_delivery_settings_validate_intervals_and_positive_values():
    import pytest
    from pydantic import ValidationError
    for kwargs in (
        {"alert_delivery_interval_seconds": 0}, {"alert_delivery_batch_size": 0},
        {"alert_retry_initial_seconds": 0}, {"alert_retry_max_seconds": 0},
        {"alert_retry_ttl_seconds": 0}, {"alert_retry_initial_seconds": 3601},
        {"alert_retry_ttl_seconds": 3599},
    ):
        with pytest.raises(ValidationError):
            Settings(**kwargs)


def test_delivery_settings_environment(monkeypatch):
    monkeypatch.setenv("ALERT_DELIVERY_INTERVAL_SECONDS", "15")
    monkeypatch.setenv("ALERT_DELIVERY_BATCH_SIZE", "30")
    monkeypatch.setenv("ALERT_RETRY_INITIAL_SECONDS", "120")
    monkeypatch.setenv("ALERT_RETRY_MAX_SECONDS", "1800")
    monkeypatch.setenv("ALERT_RETRY_TTL_SECONDS", "7200")
    settings = Settings()
    assert (settings.alert_delivery_interval_seconds, settings.alert_delivery_batch_size,
            settings.alert_retry_initial_seconds, settings.alert_retry_max_seconds,
            settings.alert_retry_ttl_seconds) == (15, 30, 120, 1800, 7200)
