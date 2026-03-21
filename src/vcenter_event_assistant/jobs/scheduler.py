"""Background polling jobs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from sqlalchemy import select

from vcenter_event_assistant.db.models import VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.ingestion import (
    ingest_events_for_vcenter,
    ingest_metrics_for_vcenter,
    list_enabled_vcenters,
    purge_old_metrics,
)
from vcenter_event_assistant.settings import get_settings

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


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
                n = await purge_old_metrics(session)
                if n:
                    logger.info("purged old metric samples count=%s", n)
        except Exception:
            logger.exception("purge failed")

    scheduler.add_job(poll_events, "interval", seconds=settings.event_poll_interval_seconds, id="poll_events")
    scheduler.add_job(poll_perf, "interval", seconds=settings.perf_sample_interval_seconds, id="poll_perf")
    scheduler.add_job(purge, "interval", hours=6, id="purge_metrics")
    scheduler.start()
    app.state.scheduler = scheduler
    return scheduler


def shutdown_scheduler(app: "FastAPI") -> None:
    sched = getattr(app.state, "scheduler", None)
    if sched is not None:
        sched.shutdown(wait=False)
