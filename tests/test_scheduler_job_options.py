"""スケジューラジョブの APScheduler オプションと設定連動。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vcenter_event_assistant.jobs.scheduler import setup_scheduler
from vcenter_event_assistant.services.ingest_runner import ingest_for_enabled_vcenters
from vcenter_event_assistant.settings import Settings

_INTERVAL_JOB_IDS = frozenset(
    {"poll_events", "poll_perf", "evaluate_alerts", "purge_metrics"},
)


@pytest.mark.asyncio
async def test_setup_scheduler_interval_jobs_use_coalesce_and_max_instances_one() -> None:
    app = MagicMock()
    scheduler = setup_scheduler(app, Settings())
    try:
        for job_id in _INTERVAL_JOB_IDS:
            job = scheduler.get_job(job_id)
            assert job is not None, job_id
            assert job.coalesce is True, job_id
            assert job.max_instances == 1, job_id
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_setup_scheduler_purge_uses_purge_interval_hours() -> None:
    app = MagicMock()
    settings = Settings(purge_interval_hours=12)
    scheduler = setup_scheduler(app, settings)
    try:
        job = scheduler.get_job("purge_metrics")
        assert job is not None
        assert job.trigger.interval.total_seconds() == 12 * 3600
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_ingest_for_enabled_vcenters_uses_gather_with_semaphore() -> None:
    settings = Settings(ingestion_concurrency=2)
    ingest_fn = AsyncMock(return_value=1)

    class _Vc:
        def __init__(self, vid: int, name: str) -> None:
            self.id = vid
            self.name = name

    with (
        patch(
            "vcenter_event_assistant.services.ingest_runner.list_enabled_vcenters",
            new=AsyncMock(return_value=[_Vc(1, "a"), _Vc(2, "b"), _Vc(3, "c")]),
        ),
        patch(
            "vcenter_event_assistant.services.ingest_runner.session_scope",
        ) as mock_session_scope,
        patch(
            "vcenter_event_assistant.services.ingest_runner.asyncio.gather",
            new=AsyncMock(return_value=[1, 1, 1]),
        ) as mock_gather,
        patch(
            "vcenter_event_assistant.services.ingest_runner.asyncio.Semaphore",
        ) as mock_semaphore,
    ):
        mock_session = AsyncMock()
        mock_session_scope.return_value.__aenter__.return_value = mock_session
        mock_session_scope.return_value.__aexit__.return_value = None

        total = await ingest_for_enabled_vcenters(
            settings,
            ingest_fn,
            success_log="ok vcenter=%s count=%s",
            failure_log="fail vcenter_id=%s",
        )

    mock_semaphore.assert_called_once_with(2)
    mock_gather.assert_awaited_once()
    assert len(mock_gather.call_args.args) == 3
    assert total == 3
