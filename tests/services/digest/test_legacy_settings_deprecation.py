"""レガシーダイジェスト設定の使用検知と起動 WARNING。"""

from __future__ import annotations

import logging

import pytest

from vcenter_event_assistant.services.digest.legacy_settings_deprecation import (
    LEGACY_DIGEST_SETTINGS_REMOVAL_VERSION,
    legacy_digest_env_vars_in_use,
    warn_if_legacy_digest_settings_in_use,
)
from vcenter_event_assistant.settings import Settings


def test_legacy_digest_env_vars_in_use_none_when_defaults() -> None:
    assert legacy_digest_env_vars_in_use(Settings()) == ()


def test_legacy_digest_env_vars_in_use_scheduler_enabled_only() -> None:
    assert legacy_digest_env_vars_in_use(
        Settings(digest_scheduler_enabled=True, digest_daily_enabled=True)
    ) == ("DIGEST_SCHEDULER_ENABLED",)


def test_legacy_digest_env_vars_in_use_legacy_daily_path() -> None:
    assert legacy_digest_env_vars_in_use(
        Settings(
            digest_scheduler_enabled=True,
            digest_daily_enabled=False,
            digest_cron="0 6 * * *",
        )
    ) == ("DIGEST_SCHEDULER_ENABLED", "DIGEST_CRON")


def test_warn_if_legacy_digest_settings_in_use_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    warn_if_legacy_digest_settings_in_use(
        Settings(digest_scheduler_enabled=True, digest_daily_enabled=False)
    )
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    assert "DIGEST_SCHEDULER_ENABLED" in record.message
    assert "DIGEST_CRON" in record.message
    assert LEGACY_DIGEST_SETTINGS_REMOVAL_VERSION in record.message


def test_warn_if_legacy_digest_settings_in_use_silent_when_not_used(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    warn_if_legacy_digest_settings_in_use(Settings())
    assert caplog.records == []
