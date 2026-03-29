"""ダイジェスト用 IANA タイムゾーン解決（Markdown 表示と集計ウィンドウで共有）。"""

from __future__ import annotations

import logging

from zoneinfo import ZoneInfo

from vcenter_event_assistant.settings import Settings

_logger = logging.getLogger(__name__)

# 無効 TZ フォールバック時も ``ZoneInfo`` で統一（``datetime.timezone.utc`` と混在させない）
_UTC_ZONE = ZoneInfo("UTC")


def _strip_opt(s: str | None) -> str:
    return (s or "").strip()


def resolve_digest_timezone(settings: Settings) -> tuple[ZoneInfo, str]:
    """
    ``DIGEST_DISPLAY_TIMEZONE`` を ``ZoneInfo`` に解決する。

    無効な IANA 名のときは UTC にフォールバックし警告ログを出す。
    """
    name = _strip_opt(settings.digest_display_timezone) or "UTC"
    try:
        return ZoneInfo(name), name
    except KeyError:
        _logger.warning(
            "無効な DIGEST_DISPLAY_TIMEZONE=%r のため UTC にフォールバックします",
            name,
        )
        return _UTC_ZONE, "UTC"
