"""起動時セキュリティ設定検証。"""

from __future__ import annotations

import pytest

from vcenter_event_assistant.security_startup import (
    SecurityConfigurationError,
    validate_startup_settings,
)
from vcenter_event_assistant.settings import Settings


def test_production_requires_secret_key() -> None:
    settings = Settings(
        app_env="production",
        database_url="sqlite+aiosqlite:///:memory:",
        vea_secret_key=None,
        vea_allow_plaintext_passwords=False,
    )
    with pytest.raises(SecurityConfigurationError, match="VEA_SECRET_KEY"):
        validate_startup_settings(settings)


def test_production_rejects_mock_mode() -> None:
    settings = Settings(
        app_env="production",
        database_url="sqlite+aiosqlite:///:memory:",
        vea_secret_key="prod-secret",
        vea_allow_plaintext_passwords=False,
        mock_mode=True,
        vcenter_allowed_host_suffixes=".corp.local",
    )
    with pytest.raises(SecurityConfigurationError, match="MOCK_MODE"):
        validate_startup_settings(settings)


def test_production_rejects_weak_db_password() -> None:
    settings = Settings(
        app_env="production",
        database_url="postgresql+asyncpg://vea:vea@postgres:5432/vcenter_event_assistant",
        vea_secret_key="prod-secret",
        vea_allow_plaintext_passwords=False,
        vcenter_allowed_host_suffixes=".corp.local",
    )
    with pytest.raises(SecurityConfigurationError, match="weak default password"):
        validate_startup_settings(settings)


def test_production_rejects_plaintext_password_flag() -> None:
    settings = Settings(
        app_env="production",
        database_url="sqlite+aiosqlite:///:memory:",
        vea_secret_key="prod-secret",
        vea_allow_plaintext_passwords=True,
        vcenter_allowed_host_suffixes=".corp.local",
    )
    with pytest.raises(SecurityConfigurationError, match="VEA_ALLOW_PLAINTEXT_PASSWORDS"):
        validate_startup_settings(settings)


def test_production_requires_host_suffixes() -> None:
    settings = Settings(
        app_env="production",
        database_url="sqlite+aiosqlite:///:memory:",
        vea_secret_key="prod-secret",
        vea_allow_plaintext_passwords=False,
        vcenter_allowed_host_suffixes="",
    )
    with pytest.raises(SecurityConfigurationError, match="VCENTER_ALLOWED_HOST_SUFFIXES"):
        validate_startup_settings(settings)


def test_development_allows_missing_secret_with_plaintext_flag() -> None:
    settings = Settings(
        app_env="development",
        database_url="sqlite+aiosqlite:///:memory:",
        vea_allow_plaintext_passwords=True,
    )
    validate_startup_settings(settings)
