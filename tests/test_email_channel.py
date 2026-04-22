import pytest
from unittest.mock import patch
from vcenter_event_assistant.services.notification.email_channel import EmailChannel
from vcenter_event_assistant.db.models import AlertRule, AlertState
from vcenter_event_assistant.settings import get_settings

@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

@pytest.mark.asyncio
async def test_email_channel_send_success(monkeypatch):
    # 設定のモック
    monkeypatch.setenv("SMTP_HOST", "smtp.test.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pass")
    monkeypatch.setenv("ALERT_EMAIL_TO", "ops@example.com")
    
    channel = EmailChannel()
    rule = AlertRule(name="Test Rule")
    state = AlertState(state="firing")
    
    with patch("smtplib.SMTP") as mock_smtp:
        instance = mock_smtp.return_value.__enter__.return_value
        await channel.notify(rule, state, "Subject", "Body")
        
        instance.starttls.assert_called_once()
        instance.login.assert_called_once_with("user", "pass")
        instance.send_message.assert_called_once()
        # メッセージの内容確認
        sent_msg = instance.send_message.call_args[0][0]
        assert sent_msg["To"] == "ops@example.com"
        assert sent_msg["Subject"] == "Subject"

@pytest.mark.asyncio
async def test_email_channel_skips_if_no_host(monkeypatch, caplog):
    monkeypatch.setenv("SMTP_HOST", "")
    channel = EmailChannel()
    await channel.notify(AlertRule(), AlertState(), "S", "B")
    assert "SMTP_HOST is not set" in caplog.text

@pytest.mark.asyncio
async def test_email_channel_fails_on_smtp_error(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test.com")
    monkeypatch.setenv("ALERT_EMAIL_TO", "ops@example.com")
    
    channel = EmailChannel()
    with patch("smtplib.SMTP") as mock_smtp:
        instance = mock_smtp.return_value.__enter__.return_value
        instance.send_message.side_effect = Exception("SMTP Error")
        
        with pytest.raises(Exception, match="SMTP Error"):
            await channel.notify(AlertRule(), AlertState(), "S", "B")
