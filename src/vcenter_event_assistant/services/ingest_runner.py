"""取り込みジョブのオーケストレーション（手動 API・スケジューラ共通）。"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select

from vcenter_event_assistant.db.models import VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.ingestion import (
    ingest_events_for_vcenter,
    ingest_metrics_for_vcenter,
    list_enabled_vcenters,
)
from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)

_ingest_guard = asyncio.Lock()
_ingest_busy = False


class IngestBusyError(Exception):
    """別の取り込みが実行中で、排他実行を開始できない。"""


@dataclass(frozen=True)
class IngestRunResult:
    """全有効 vCenter に対する手動取り込みの集計結果。"""

    events_inserted: int
    metrics_inserted: int


@asynccontextmanager
async def _ingest_run_slot(*, policy: Literal["reject", "skip"]):
    """取り込みの排他スロットを確保する。

    Args:
        policy: ``reject`` は競合時に ``IngestBusyError``、``skip`` は ``yield False``。
    """
    global _ingest_busy

    async with _ingest_guard:
        if _ingest_busy:
            if policy == "reject":
                raise IngestBusyError()
            yield False
            return
        _ingest_busy = True

    try:
        yield True
    finally:
        async with _ingest_guard:
            _ingest_busy = False


async def ingest_for_enabled_vcenters(
    settings: Settings,
    ingest_fn: Callable[..., Awaitable[int]],
    *,
    success_log: str,
    failure_log: str,
) -> int:
    """有効 vCenter ごとに取り込み関数を並行実行する（失敗は vCenter 単位で分離）。

    Returns:
        全 vCenter で挿入された行数の合計。
    """
    async with session_scope(settings=settings) as session:
        vcenters = await list_enabled_vcenters(session)
        ids = [v.id for v in vcenters]

    sem = asyncio.Semaphore(settings.ingestion_concurrency)

    async def _one(vid: uuid.UUID) -> int:
        async with sem:
            try:
                async with session_scope(settings=settings) as session:
                    res = await session.execute(select(VCenter).where(VCenter.id == vid))
                    vc = res.scalar_one()
                    n = await ingest_fn(session, vc, settings=settings)
                    logger.info(success_log, vc.name, n)
                    return n
            except Exception:
                logger.exception(failure_log, vid)
                return 0

    counts = await asyncio.gather(*(_one(vid) for vid in ids))
    return sum(counts)


async def run_ingest_events(settings: Settings) -> int | None:
    """有効 vCenter からイベントを取り込む。競合時は ``None``（スキップ）。"""
    async with _ingest_run_slot(policy="skip") as acquired:
        if not acquired:
            logger.debug("event ingest skipped: another ingest is running")
            return None
        return await ingest_for_enabled_vcenters(
            settings,
            ingest_events_for_vcenter,
            success_log="events ingested vcenter=%s count=%s",
            failure_log="event poll failed vcenter_id=%s",
        )


async def run_ingest_metrics(settings: Settings) -> int | None:
    """有効 vCenter からメトリクスを取り込む。競合時は ``None``（スキップ）。"""
    async with _ingest_run_slot(policy="skip") as acquired:
        if not acquired:
            logger.debug("metrics ingest skipped: another ingest is running")
            return None
        return await ingest_for_enabled_vcenters(
            settings,
            ingest_metrics_for_vcenter,
            success_log="metrics ingested vcenter=%s count=%s",
            failure_log="perf poll failed vcenter_id=%s",
        )


async def run_ingest_all(settings: Settings) -> IngestRunResult:
    """全有効 vCenter のイベント・メトリクスを順に取り込む（手動 API 用）。

    Raises:
        IngestBusyError: 別の取り込みが実行中。
    """
    async with _ingest_run_slot(policy="reject"):
        events_inserted = await ingest_for_enabled_vcenters(
            settings,
            ingest_events_for_vcenter,
            success_log="events ingested vcenter=%s count=%s",
            failure_log="event poll failed vcenter_id=%s",
        )
        metrics_inserted = await ingest_for_enabled_vcenters(
            settings,
            ingest_metrics_for_vcenter,
            success_log="metrics ingested vcenter=%s count=%s",
            failure_log="perf poll failed vcenter_id=%s",
        )
    return IngestRunResult(
        events_inserted=events_inserted,
        metrics_inserted=metrics_inserted,
    )
