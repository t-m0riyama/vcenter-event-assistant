"""Recalculate stored notable scores when per-type rules change."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import EventRecord, EventScoreRule
from vcenter_event_assistant.rules.notable import final_notable_score


async def load_event_score_delta_map(session: AsyncSession) -> dict[str, int]:
    res = await session.execute(select(EventScoreRule.event_type, EventScoreRule.score_delta))
    return {str(et): int(d) for et, d in res.all()}


async def recalculate_notable_scores_for_event_type(
    session: AsyncSession,
    *,
    event_type: str,
    score_delta: int,
) -> int:
    """Recompute ``notable_score`` for all rows matching ``event_type``. Returns rows updated."""
    res = await session.execute(select(EventRecord).where(EventRecord.event_type == event_type))
    rows = list(res.scalars().all())
    for row in rows:
        row.notable_score = final_notable_score(
            event_type=row.event_type,
            severity=row.severity,
            message=row.message,
            score_delta=score_delta,
        )
    return len(rows)
