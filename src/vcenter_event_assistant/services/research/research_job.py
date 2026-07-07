"""事前調査ジョブ: 高スコア event_type を選び WEB 調査してキャッシュする。

取り込み・アラート評価とは独立の専用ジョブとして動く（外部 I/O を他パイプラインに
混ぜない）。検索プロバイダ未構成（閉域網・API キーなし）では即 no-op。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import EventRecord, EventTypeResearch
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.research.research_service import (
    research_event_type,
    research_is_fresh,
)
from vcenter_event_assistant.services.research.search_provider import (
    build_search_provider,
)
from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)


async def select_event_types_needing_research(
    session: AsyncSession,
    *,
    settings: Settings,
    now: datetime | None = None,
) -> list[str]:
    """調査対象の event_type をスコア降順で最大 ``research_max_per_cycle`` 件返す。

    対象: lookback 内に ``notable_score >= research_event_score_threshold`` の
    イベントがあり、調査キャッシュが存在しないか TTL 切れの event_type。
    """
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(hours=settings.research_event_lookback_hours)

    res = await session.execute(
        select(
            EventRecord.event_type,
            func.max(EventRecord.notable_score).label("max_score"),
        )
        .where(
            EventRecord.occurred_at >= cutoff,
            EventRecord.notable_score >= settings.research_event_score_threshold,
        )
        .group_by(EventRecord.event_type)
        .order_by(desc("max_score"))
    )
    candidates = [row[0] for row in res.all()]
    if not candidates:
        return []

    res = await session.execute(
        select(EventTypeResearch).where(EventTypeResearch.event_type.in_(candidates))
    )
    research_by_type = {row.event_type: row for row in res.scalars().all()}

    targets: list[str] = []
    for event_type in candidates:
        row = research_by_type.get(event_type)
        if row is not None and research_is_fresh(row, settings=settings, now=current):
            continue
        targets.append(event_type)
        if len(targets) >= settings.research_max_per_cycle:
            break
    return targets


async def run_research_cycle(settings: Settings) -> int:
    """事前調査を 1 サイクル実行し、調査した event_type 数を返す。

    検索プロバイダ未構成では 0 を返す（機能無効）。event_type ごとに失敗を分離する。
    """
    provider = build_search_provider(settings)
    if provider is None:
        logger.debug("web research skipped: search provider not configured")
        return 0

    async with session_scope(settings=settings) as session:
        targets = await select_event_types_needing_research(session, settings=settings)

    if not targets:
        return 0

    researched = 0
    for event_type in targets:
        try:
            async with session_scope(settings=settings) as session:
                row = await research_event_type(
                    session,
                    event_type,
                    settings=settings,
                    provider=provider,
                )
            logger.info(
                "web research completed event_type=%s status=%s",
                event_type,
                row.status,
            )
            researched += 1
        except Exception:
            logger.exception("web research failed event_type=%s", event_type)
    return researched
