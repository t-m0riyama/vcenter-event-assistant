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


@pytest.mark.asyncio
async def test_delivery_job_registered_independently():
    settings = Settings(alert_delivery_interval_seconds=15)
    scheduler = setup_scheduler(MagicMock(), settings)
    try:
        delivery = scheduler.get_job("deliver_alert_notifications")
        assert delivery is not None
        assert delivery.max_instances == 1 and delivery.coalesce is True
        assert delivery.trigger.interval.total_seconds() == 15
        assert scheduler.get_job("evaluate_alerts") is not None
    finally:
        scheduler.shutdown(wait=False)
