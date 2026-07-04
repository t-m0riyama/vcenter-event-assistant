"""バックグラウンド定期ジョブ。

イベント取り込み・メトリクス収集・アラート評価・保持期間パージ・
ダイジェスト生成を APScheduler でスケジュールする。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from sqlalchemy import select

from vcenter_event_assistant.db.models import VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alerting.alert_eval import AlertEvaluator
from vcenter_event_assistant.services.digest.digest_run import run_digest_once
from vcenter_event_assistant.services.digest.digest_timezone import resolve_digest_timezone
from vcenter_event_assistant.services.digest.digest_window import (
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
from vcenter_event_assistant.settings import Settings

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

# 全スケジュールジョブに共通の APScheduler オプション
_JOB_OPTIONS = {"coalesce": True, "max_instances": 1}


async def _ingest_for_enabled_vcenters(
    settings: Settings,
    ingest_fn: Callable[..., Awaitable[int]],
    *,
    success_log: str,
    failure_log: str,
) -> None:
    """有効 vCenter ごとに取り込み関数を並行実行する（失敗は vCenter 単位で分離）。"""
    async with session_scope(settings=settings) as session:
        vcenters = await list_enabled_vcenters(session)
        ids = [v.id for v in vcenters]

    sem = asyncio.Semaphore(settings.ingestion_concurrency)

    async def _one(vid: int) -> None:
        async with sem:
            try:
                async with session_scope(settings=settings) as session:
                    res = await session.execute(select(VCenter).where(VCenter.id == vid))
                    vc = res.scalar_one()
                    n = await ingest_fn(session, vc, settings=settings)
                    logger.info(success_log, vc.name, n)
            except Exception:
                logger.exception(failure_log, vid)

    await asyncio.gather(*(_one(vid) for vid in ids))


async def poll_events(settings: Settings) -> None:
    """有効 vCenter からイベントを取り込む。"""
    await _ingest_for_enabled_vcenters(
        settings,
        ingest_events_for_vcenter,
        success_log="events ingested vcenter=%s count=%s",
        failure_log="event poll failed vcenter_id=%s",
    )


async def poll_perf(settings: Settings) -> None:
    """有効 vCenter からメトリクスを取り込む。"""
    await _ingest_for_enabled_vcenters(
        settings,
        ingest_metrics_for_vcenter,
        success_log="metrics ingested vcenter=%s count=%s",
        failure_log="perf poll failed vcenter_id=%s",
    )


async def purge_retention(settings: Settings) -> None:
    """保持期間を超えたイベント・メトリクスを削除する。"""
    try:
        async with session_scope(settings=settings) as session:
            n_ev = await purge_old_events(session, settings=settings)
            if n_ev:
                logger.info("purged old events count=%s", n_ev)
            n_m = await purge_old_metrics(session, settings=settings)
            if n_m:
                logger.info("purged old metric samples count=%s", n_m)
    except Exception:
        logger.exception("purge failed")


async def evaluate_alerts(settings: Settings) -> None:
    """全アラートルールを評価する。"""
    try:
        evaluator = AlertEvaluator(settings)
        await evaluator.evaluate_all()
    except Exception:
        logger.exception("alert evaluation job failed")


async def run_daily_digest(settings: Settings) -> None:
    """設定 TZ の直前暦日を対象に日次ダイジェストを 1 件生成する。"""
    tz, _ = resolve_digest_timezone(settings)
    fr, to = zoned_yesterday_window(None, tz)
    try:
        async with session_scope(settings=settings) as session:
            row = await run_digest_once(
                session,
                kind="daily",
                from_utc=fr,
                to_utc=to,
                settings=settings,
            )
        logger.info(
            "digest created kind=daily id=%s period=%s..%s",
            row.id,
            fr.isoformat(),
            to.isoformat(),
        )
    except Exception:
        logger.exception("daily digest job failed")


async def run_weekly_digest(settings: Settings) -> None:
    """設定 TZ の日曜 0:00 始まりの直前暦週を対象に週次ダイジェストを 1 件生成する。"""
    tz, _ = resolve_digest_timezone(settings)
    fr, to = zoned_previous_week_window(None, tz)
    try:
        async with session_scope(settings=settings) as session:
            row = await run_digest_once(
                session,
                kind="weekly",
                from_utc=fr,
                to_utc=to,
                settings=settings,
            )
        logger.info(
            "digest created kind=weekly id=%s period=%s..%s",
            row.id,
            fr.isoformat(),
            to.isoformat(),
        )
    except Exception:
        logger.exception("weekly digest job failed")


async def run_monthly_digest(settings: Settings) -> None:
    """設定 TZ の直前暦月を対象に月次ダイジェストを 1 件生成する。"""
    tz, _ = resolve_digest_timezone(settings)
    fr, to = zoned_previous_calendar_month_window(None, tz)
    try:
        async with session_scope(settings=settings) as session:
            row = await run_digest_once(
                session,
                kind="monthly",
                from_utc=fr,
                to_utc=to,
                settings=settings,
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
            kwargs={"settings": settings},
            **_JOB_OPTIONS,
        )
    if settings.digest_weekly_enabled:
        scheduler.add_job(
            run_weekly_digest,
            CronTrigger.from_crontab(settings.digest_weekly_cron),
            id="digest_weekly",
            kwargs={"settings": settings},
            **_JOB_OPTIONS,
        )
    if settings.digest_monthly_enabled:
        scheduler.add_job(
            run_monthly_digest,
            CronTrigger.from_crontab(settings.digest_monthly_cron),
            id="digest_monthly",
            kwargs={"settings": settings},
            **_JOB_OPTIONS,
        )


def setup_scheduler(app: "FastAPI", settings: Settings) -> AsyncIOScheduler:
    """APScheduler に定期ジョブを登録し、``app.state.scheduler`` に格納する。

    Args:
        app: スケジューラ参照を保持する FastAPI アプリ。
        settings: ジョブへ渡すアプリ設定。

    Returns:
        起動済みの ``AsyncIOScheduler``。
    """
    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        poll_events,
        "interval",
        seconds=settings.event_poll_interval_seconds,
        id="poll_events",
        kwargs={"settings": settings},
        **_JOB_OPTIONS,
    )
    scheduler.add_job(
        poll_perf,
        "interval",
        seconds=settings.perf_sample_interval_seconds,
        id="poll_perf",
        kwargs={"settings": settings},
        **_JOB_OPTIONS,
    )
    scheduler.add_job(
        evaluate_alerts,
        "interval",
        seconds=settings.alert_eval_interval_seconds,
        id="evaluate_alerts",
        kwargs={"settings": settings},
        **_JOB_OPTIONS,
    )
    scheduler.add_job(
        purge_retention,
        "interval",
        hours=settings.purge_interval_hours,
        id="purge_metrics",
        kwargs={"settings": settings},
        **_JOB_OPTIONS,
    )
    add_digest_cron_jobs(scheduler, settings)
    scheduler.start()
    app.state.scheduler = scheduler
    return scheduler


def shutdown_scheduler(app: "FastAPI") -> None:
    """``app.state.scheduler`` が存在すれば非同期シャットダウンする。

    Args:
        app: ``setup_scheduler`` で scheduler を登録した FastAPI アプリ。
    """
    sched = getattr(app.state, "scheduler", None)
    if sched is not None:
        sched.shutdown(wait=False)
