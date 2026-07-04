"""アラート評価スケジューラジョブの登録オプション。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from vcenter_event_assistant.jobs.scheduler import setup_scheduler
from vcenter_event_assistant.settings import get_settings


@pytest.mark.asyncio
async def test_evaluate_alerts_job_uses_coalesce() -> None:
    app = MagicMock()
    scheduler = setup_scheduler(app, get_settings())
    try:
        job = scheduler.get_job("evaluate_alerts")
        assert job is not None
        assert job.coalesce is True
    finally:
        scheduler.shutdown(wait=False)
