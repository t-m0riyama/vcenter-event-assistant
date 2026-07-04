"""アラート評価スケジューラジョブの登録オプション。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from vcenter_event_assistant.jobs.scheduler import setup_scheduler
from vcenter_event_assistant.settings import Settings


@pytest.mark.asyncio
async def test_evaluate_alerts_job_uses_coalesce_and_max_instances_one() -> None:
    app = MagicMock()
    scheduler = setup_scheduler(app, Settings())
    try:
        job = scheduler.get_job("evaluate_alerts")
        assert job is not None
        assert job.coalesce is True
        assert job.max_instances == 1
    finally:
        scheduler.shutdown(wait=False)
