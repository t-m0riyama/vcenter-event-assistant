"""スケジューラジョブの APScheduler オプションと設定連動。"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from vcenter_event_assistant.db.models import VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.jobs.scheduler import setup_scheduler
from vcenter_event_assistant.services.ingest_runner import ingest_for_enabled_vcenters
from vcenter_event_assistant.settings import Settings

_INTERVAL_JOB_IDS = frozenset(
    {"poll_events", "poll_perf", "evaluate_alerts", "purge_metrics"},
)


_INTERVAL_JOB_MISFIRE = {
    "poll_events": 60,  # default 120s interval / 2
    "poll_perf": 150,  # default 300s / 2
    "evaluate_alerts": 30,  # default 60s / 2
    "purge_metrics": 6 * 3600 // 2,  # default 6h / 2
}


@pytest.mark.asyncio
async def test_setup_scheduler_interval_jobs_use_coalesce_and_max_instances_one() -> (
    None
):
    app = MagicMock()
    scheduler = setup_scheduler(app, Settings())
    try:
        for job_id in _INTERVAL_JOB_IDS:
            job = scheduler.get_job(job_id)
            assert job is not None, job_id
            assert job.coalesce is True, job_id
            assert job.max_instances == 1, job_id
            assert job.misfire_grace_time == _INTERVAL_JOB_MISFIRE[job_id], job_id
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_setup_scheduler_interval_misfire_scales_with_settings() -> None:
    app = MagicMock()
    settings = Settings(
        event_poll_interval_seconds=200,
        perf_sample_interval_seconds=400,
        alert_eval_interval_seconds=100,
        purge_interval_hours=4,
    )
    scheduler = setup_scheduler(app, settings)
    try:
        assert scheduler.get_job("poll_events").misfire_grace_time == 100
        assert scheduler.get_job("poll_perf").misfire_grace_time == 200
        assert scheduler.get_job("evaluate_alerts").misfire_grace_time == 50
        assert scheduler.get_job("purge_metrics").misfire_grace_time == 4 * 3600 // 2
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
async def test_ingest_for_enabled_vcenters_limits_concurrency() -> None:
    settings = Settings(ingestion_concurrency=2)
    active = 0
    peak = 0
    started: list[int] = []
    two_started = asyncio.Event()
    release = asyncio.Event()

    async with session_scope(settings=settings) as session:
        session.add_all(
            [
                VCenter(
                    name=str(vid), host=f"vc{vid}.example", username="u", password="p"
                )
                for vid in (1, 2, 3)
            ]
        )

    async def ingest_fn(session, vc, *, settings):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        started.append(int(vc.name))
        if active == 2:
            two_started.set()
        try:
            await release.wait()
            return int(vc.name)
        finally:
            active -= 1

    task = asyncio.create_task(
        ingest_for_enabled_vcenters(
            settings,
            ingest_fn,
            success_log="ok vcenter=%s count=%s",
            failure_log="fail vcenter_id=%s",
        )
    )
    try:
        await asyncio.wait_for(two_started.wait(), timeout=2)
        assert len(started) == 2
        assert peak == 2
    finally:
        release.set()
        total = await asyncio.wait_for(task, timeout=2)

    assert sorted(started) == [1, 2, 3]
    assert peak == 2
    assert active == 0
    assert total == 6


@pytest.mark.asyncio
async def test_setup_scheduler_omits_web_research_job_without_provider() -> None:
    app = MagicMock()
    scheduler = setup_scheduler(app, Settings())
    try:
        assert scheduler.get_job("web_research") is None
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_setup_scheduler_adds_web_research_job_with_provider() -> None:
    app = MagicMock()
    scheduler = setup_scheduler(
        app, Settings(tavily_api_key="tvly-test", web_research_enabled=True)
    )
    try:
        job = scheduler.get_job("web_research")
        assert job is not None
        assert job.coalesce is True
        assert job.max_instances == 1
        assert job.misfire_grace_time == 300  # default 600s interval / 2
    finally:
        scheduler.shutdown(wait=False)
