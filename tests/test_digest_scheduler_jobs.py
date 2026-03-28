"""ダイジェスト用 APScheduler ジョブ登録（add_digest_cron_jobs）。"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from vcenter_event_assistant.jobs.scheduler import add_digest_cron_jobs
from vcenter_event_assistant.settings import Settings

_DIGEST_IDS = frozenset({"digest_daily", "digest_weekly", "digest_monthly"})


def _digest_job_ids(scheduler: AsyncIOScheduler) -> set[str]:
    return {j.id for j in scheduler.get_jobs() if j.id in _DIGEST_IDS}


def test_add_digest_cron_jobs_none_when_all_disabled() -> None:
    s = Settings(
        digest_daily_enabled=False,
        digest_scheduler_enabled=False,
        digest_weekly_enabled=False,
        digest_monthly_enabled=False,
    )
    sched = AsyncIOScheduler()
    add_digest_cron_jobs(sched, s)
    assert _digest_job_ids(sched) == set()


def test_add_digest_cron_jobs_daily_legacy_only() -> None:
    s = Settings(
        digest_daily_enabled=False,
        digest_scheduler_enabled=True,
        digest_cron="0 7 * * *",
        digest_weekly_enabled=False,
        digest_monthly_enabled=False,
    )
    sched = AsyncIOScheduler()
    add_digest_cron_jobs(sched, s)
    assert _digest_job_ids(sched) == {"digest_daily"}


def test_add_digest_cron_jobs_all_three_enabled() -> None:
    s = Settings(
        digest_daily_enabled=True,
        digest_weekly_enabled=True,
        digest_monthly_enabled=True,
    )
    sched = AsyncIOScheduler()
    add_digest_cron_jobs(sched, s)
    assert _digest_job_ids(sched) == {"digest_daily", "digest_weekly", "digest_monthly"}
