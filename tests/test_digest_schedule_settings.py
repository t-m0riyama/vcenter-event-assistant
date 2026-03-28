"""ダイジェストスケジュール設定の実効 enabled / cron（レガシー互換）。"""

from __future__ import annotations

from vcenter_event_assistant.settings import Settings


def test_effective_daily_uses_new_when_daily_enabled() -> None:
    s = Settings(
        digest_daily_enabled=True,
        digest_daily_cron="1 2 * * *",
        digest_scheduler_enabled=True,
        digest_cron="9 9 * * *",
    )
    assert s.effective_digest_daily_enabled is True
    assert s.effective_digest_daily_cron == "1 2 * * *"


def test_effective_daily_legacy_only() -> None:
    s = Settings(
        digest_daily_enabled=False,
        digest_scheduler_enabled=True,
        digest_cron="0 6 * * *",
        digest_daily_cron="0 7 * * *",
    )
    assert s.effective_digest_daily_enabled is True
    assert s.effective_digest_daily_cron == "0 6 * * *"


def test_effective_daily_both_disabled() -> None:
    s = Settings(digest_daily_enabled=False, digest_scheduler_enabled=False)
    assert s.effective_digest_daily_enabled is False


def test_effective_daily_cron_when_both_disabled() -> None:
    """無効時は cron 実効値は参照されないが digest_daily_cron を返す。"""
    s = Settings(
        digest_daily_enabled=False,
        digest_scheduler_enabled=False,
        digest_daily_cron="0 7 * * *",
        digest_cron="0 6 * * *",
    )
    assert s.effective_digest_daily_cron == "0 7 * * *"
