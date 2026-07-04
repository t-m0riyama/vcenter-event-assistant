"""レガシーダイジェスト環境変数（``DIGEST_SCHEDULER_*``）の廃止予告。"""

from __future__ import annotations

import logging

from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)

# 0.1.0 で廃止予告。2 リリース後（architecture-improvement-plan 4-5）に削除。
LEGACY_DIGEST_SETTINGS_REMOVAL_VERSION = "0.3.0"


def legacy_digest_env_vars_in_use(settings: Settings) -> tuple[str, ...]:
    """実際の挙動に効いているレガシー環境変数名を返す。"""
    in_use: list[str] = []
    if settings.digest_scheduler_enabled:
        in_use.append("DIGEST_SCHEDULER_ENABLED")
        if not settings.digest_daily_enabled:
            in_use.append("DIGEST_CRON")
    return tuple(in_use)


def warn_if_legacy_digest_settings_in_use(settings: Settings) -> None:
    """レガシー設定が有効なら起動時 WARNING を 1 回出す。"""
    legacy = legacy_digest_env_vars_in_use(settings)
    if not legacy:
        return
    logger.warning(
        "Legacy digest env vars in use (%s). Migrate to DIGEST_DAILY_ENABLED and "
        "DIGEST_DAILY_CRON. Removal planned in v%s.",
        ", ".join(legacy),
        LEGACY_DIGEST_SETTINGS_REMOVAL_VERSION,
    )
