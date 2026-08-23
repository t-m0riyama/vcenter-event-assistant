"""起動時セキュリティ設定の検証。"""

from __future__ import annotations

import logging
import re

from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)

_WEAK_DB_PASSWORDS = frozenset({"postgres", "vea", "changeme", "password", "admin"})
_POSTGRES_URL_RE = re.compile(
    r"postgresql\+asyncpg://[^:]+:(?P<pw>[^@]+)@",
    re.IGNORECASE,
)


class SecurityConfigurationError(RuntimeError):
    """本番向け必須設定が満たされていない。"""


def passwords_may_be_stored(settings: Settings) -> bool:
    """vCenter パスワードを DB に保存してよいか（暗号化または明示許可）。"""
    if settings.vea_secret_key:
        return True
    if settings.mock_mode:
        return True
    if settings.vea_allow_plaintext_passwords:
        return True
    return False


def validate_startup_settings(settings: Settings) -> None:
    """アプリ起動前にセキュリティ関連設定を検証する。"""
    if settings.is_production:
        if settings.mock_mode:
            raise SecurityConfigurationError(
                "MOCK_MODE must not be enabled when APP_ENV=production"
            )
        if not settings.vea_secret_key:
            raise SecurityConfigurationError(
                "VEA_SECRET_KEY is required when APP_ENV=production"
            )
        if not settings.vcenter_allowed_host_suffix_list:
            raise SecurityConfigurationError(
                "VCENTER_ALLOWED_HOST_SUFFIXES is required when APP_ENV=production"
            )
        _validate_production_database_url(settings.database_url)
    elif not settings.vea_secret_key and not settings.mock_mode:
        if not settings.vea_allow_plaintext_passwords:
            logger.warning(
                "VEA_SECRET_KEY is not set and VEA_ALLOW_PLAINTEXT_PASSWORDS is false; "
                "vCenter password create/update API will be rejected until a key is configured."
            )


def _validate_production_database_url(database_url: str) -> None:
    match = _POSTGRES_URL_RE.search(database_url)
    if not match:
        return
    password = match.group("pw")
    if password.lower() in _WEAK_DB_PASSWORDS:
        raise SecurityConfigurationError(
            "DATABASE_URL contains a weak default password; set a strong credential for production"
        )
