import smtplib
from email.message import EmailMessage
from vcenter_event_assistant.db.models import AlertRule, AlertState
from vcenter_event_assistant.services.notification.base import NotificationChannel
from vcenter_event_assistant.settings import get_settings
import logging

logger = logging.getLogger(__name__)

class EmailChannel(NotificationChannel):
    async def notify(self, rule: AlertRule, state: AlertState, subject: str, body: str) -> None:
        settings = get_settings()
        
        if not settings.smtp_host:
            logger.warning("SMTP_HOST is not set. Skipping email notification.")
            return

        if not settings.alert_email_to:
            logger.warning("ALERT_EMAIL_TO is not set. Skipping email notification.")
            return

        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        msg["From"] = settings.alert_email_from
        msg["To"] = settings.alert_email_to

        # SMTP 送信 (同期ライブラリを使用するためブロッキングに注意が必要だが、
        # 現状の設計ではシンプルに進める。将来的に aiosmtplib 等への移行も検討)
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                if settings.smtp_use_tls:
                    server.starttls()
                
                if settings.smtp_username and settings.smtp_password:
                    server.login(settings.smtp_username, settings.smtp_password)
                
                server.send_message(msg)
                logger.info(f"Email notification sent: {subject}")
        except Exception as e:
            logger.error(f"Failed to send email notification: {e}")
            raise e
