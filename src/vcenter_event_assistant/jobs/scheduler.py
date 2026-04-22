"""Background polling jobs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from sqlalchemy import select

from vcenter_event_assistant.db.models import VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.digest_run import run_digest_once
from vcenter_event_assistant.services.digest_timezone import resolve_digest_timezone
from vcenter_event_assistant.services.digest_window import (
    zoned_previous_calendar_month_window,
    zoned_previous_week_window,
    zoned_yesterday_window,
)
from vcenter_event_assistant.services.ingestion import (
    ingest_events_for_vcenter,
    ingest_metrics_for_vcenter,
    list_enabled_vcenters,
    purge_old_events,
    purge_old_metrics,
)
from vcenter_event_assistant.services.alert_eval import AlertEvaluator
from vcenter_event_assistant.settings import Settings, get_settings

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


async def run_daily_digest() -> None:
    """設定 TZ の直前暦日を対象に日次ダイジェストを 1 件生成する。"""
    tz, _ = resolve_digest_timezone(get_settings())
    fr, to = zoned_yesterday_window(None, tz)
    try:
        async with session_scope() as session:
            row = await run_digest_once(
                session,
                kind="daily",
                from_utc=fr,
                to_utc=to,
                settings=get_settings(),
            )
        logger.info(
            "digest created kind=daily id=%s period=%s..%s",
            row.id,
            fr.isoformat(),
            to.isoformat(),
        )
    except Exception:
        logger.exception("daily digest job failed")


async def run_weekly_digest() -> None:
    """設定 TZ の日曜 0:00 始まりの直前暦週を対象に週次ダイジェストを 1 件生成する。"""
    tz, _ = resolve_digest_timezone(get_settings())
    fr, to = zoned_previous_week_window(None, tz)
    try:
        async with session_scope() as session:
            row = await run_digest_once(
                session,
                kind="weekly",
                from_utc=fr,
                to_utc=to,
                settings=get_settings(),
            )
        logger.info(
            "digest created kind=weekly id=%s period=%s..%s",
            row.id,
            fr.isoformat(),
            to.isoformat(),
        )
    except Exception:
        logger.exception("weekly digest job failed")


async def run_monthly_digest() -> None:
    """設定 TZ の直前暦月を対象に月次ダイジェストを 1 件生成する。"""
    tz, _ = resolve_digest_timezone(get_settings())
    fr, to = zoned_previous_calendar_month_window(None, tz)
    try:
        async with session_scope() as session:
            row = await run_digest_once(
                session,
                kind="monthly",
                from_utc=fr,
                to_utc=to,
                settings=get_settings(),
            )
        logger.info(
            "digest created kind=monthly id=%s period=%s..%s",
            row.id,
            fr.isoformat(),
            to.isoformat(),
        )
    except Exception:
        logger.exception("monthly digest job failed")


def add_digest_cron_jobs(scheduler: AsyncIOScheduler, settings: Settings) -> None:
    """
    設定に応じて日次・週次・月次のダイジェスト cron ジョブだけを ``scheduler`` に登録する。

    ``poll_events`` 等とは独立している。
    """
    if settings.effective_digest_daily_enabled:
        scheduler.add_job(
            run_daily_digest,
            CronTrigger.from_crontab(settings.effective_digest_daily_cron),
            id="digest_daily",
        )
    if settings.digest_weekly_enabled:
        scheduler.add_job(
            run_weekly_digest,
            CronTrigger.from_crontab(settings.digest_weekly_cron),
            id="digest_weekly",
        )
    if settings.digest_monthly_enabled:
        scheduler.add_job(
            run_monthly_digest,
            CronTrigger.from_crontab(settings.digest_monthly_cron),
            id="digest_monthly",
        )


def setup_scheduler(app: "FastAPI") -> AsyncIOScheduler:
    settings = get_settings()
    scheduler = AsyncIOScheduler()

    async def poll_events() -> None:
        async with session_scope() as session:
            vcenters = await list_enabled_vcenters(session)
            ids = [v.id for v in vcenters]
        for vid in ids:
            try:
                async with session_scope() as session:
                    res = await session.execute(select(VCenter).where(VCenter.id == vid))
                    vc = res.scalar_one()
                    n = await ingest_events_for_vcenter(session, vc)
                    logger.info("events ingested vcenter=%s count=%s", vc.name, n)
            except Exception:
                logger.exception("event poll failed vcenter_id=%s", vid)

    async def poll_perf() -> None:
        async with session_scope() as session:
            vcenters = await list_enabled_vcenters(session)
            ids = [v.id for v in vcenters]
        for vid in ids:
            try:
                async with session_scope() as session:
                    res = await session.execute(select(VCenter).where(VCenter.id == vid))
                    vc = res.scalar_one()
                    n = await ingest_metrics_for_vcenter(session, vc)
                    logger.info("metrics ingested vcenter=%s count=%s", vc.name, n)
            except Exception:
                logger.exception("perf poll failed vcenter_id=%s", vid)

    async def purge() -> None:
        try:
            async with session_scope() as session:
                n_ev = await purge_old_events(session)
                if n_ev:
                    logger.info("purged old events count=%s", n_ev)
                n_m = await purge_old_metrics(session)
                if n_m:
                    logger.info("purged old metric samples count=%s", n_m)
        except Exception:
            logger.exception("purge failed")

    async def evaluate_alerts() -> None:
        try:
            evaluator = AlertEvaluator()
            await evaluator.evaluate_all()
        except Exception:
            logger.exception("alert evaluation job failed")

    scheduler.add_job(poll_events, "interval", seconds=settings.event_poll_interval_seconds, id="poll_events")
    scheduler.add_job(poll_perf, "interval", seconds=settings.perf_sample_interval_seconds, id="poll_perf")
    scheduler.add_job(evaluate_alerts, "interval", seconds=settings.alert_eval_interval_seconds, id="evaluate_alerts")
    scheduler.add_job(purge, "interval", hours=6, id="purge_metrics")
    add_digest_cron_jobs(scheduler, settings)
    scheduler.start()
    app.state.scheduler = scheduler
    return scheduler


def shutdown_scheduler(app: "FastAPI") -> None:
    sched = getattr(app.state, "scheduler", None)
    if sched is not None:
        sched.shutdown(wait=False)
