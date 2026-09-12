"""Atomic hot reload of the collector registry.

新しい世代を組み立ててから有効化し、スケジューラのジョブを追従させ、最後に旧世代を停止する。
順序が重要である: 先に旧世代を止めると、その間に到来した実行が停止済みプラグインを掴む。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from vcenter_event_assistant.plugins.registry import (
    CollectorRegistry,
    activate_collector_registry,
    build_collector_registry,
    get_collector_registry,
    shutdown_collector_registry,
    start_collector_registry,
)
from vcenter_event_assistant.services.plugin_settings import (
    load_collector_db_overrides_with_settings,
)
from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)

_reload_lock = asyncio.Lock()


@dataclass(frozen=True, slots=True)
class ReloadResult:
    generation: int
    job_changes: dict[str, list[str]]


async def reload_collector_registry(
    settings: Settings, *, scheduler=None
) -> ReloadResult:
    """レジストリを再構築し、原子的に差し替えてスケジューラを追従させる。

    Args:
        settings: アプリ設定。
        scheduler: 稼働中の ``AsyncIOScheduler``。``None`` ならジョブ追従はスキップする。

    Returns:
        新しい世代番号とジョブの差分内容。
    """
    from vcenter_event_assistant.jobs.scheduler import reconcile_collector_jobs

    async with _reload_lock:
        previous = get_collector_registry()
        overrides = await load_collector_db_overrides_with_settings(settings)
        # build は entry point の import を伴い同期的にブロックするためスレッドへ逃がす。
        candidate = await asyncio.to_thread(
            build_collector_registry,
            settings,
            generation=previous.generation + 1,
            db_overrides=overrides,
        )
        started = await start_collector_registry(candidate)
        activate_collector_registry(started)

        job_changes: dict[str, list[str]] = {
            "added": [],
            "removed": [],
            "rescheduled": [],
        }
        if scheduler is not None:
            job_changes = reconcile_collector_jobs(scheduler, settings, started)

        await shutdown_collector_registry(previous)
        logger.info(
            "collector registry reloaded generation=%s jobs=%s",
            started.generation,
            job_changes,
        )
        return ReloadResult(generation=started.generation, job_changes=job_changes)


async def build_initial_collector_registry(settings: Settings) -> CollectorRegistry:
    """起動時のレジストリを DB 設定込みで構築して有効化する。"""
    overrides = await load_collector_db_overrides_with_settings(settings)
    registry = await start_collector_registry(
        build_collector_registry(settings, db_overrides=overrides)
    )
    activate_collector_registry(registry)
    return registry
