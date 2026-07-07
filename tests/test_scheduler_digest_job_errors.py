"""ダイジェストスケジューラジョブの例外処理テスト。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from vcenter_event_assistant.jobs.scheduler import run_daily_digest
from vcenter_event_assistant.settings import Settings


@pytest.mark.asyncio
async def test_run_daily_digest_logs_window_calculation_errors() -> None:
    settings = Settings()

    with (
        patch(
            "vcenter_event_assistant.jobs.scheduler.zoned_yesterday_window",
            side_effect=RuntimeError("window failed"),
        ),
        patch("vcenter_event_assistant.jobs.scheduler.logger.exception") as mock_log,
    ):
        await run_daily_digest(settings)

    mock_log.assert_called_once_with("daily digest job failed")
