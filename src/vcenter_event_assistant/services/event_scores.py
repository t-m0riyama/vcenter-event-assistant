"""種別ルール変更時の notable スコア再計算。

``EventScoreRule`` の delta マップを読み込み、保存済みイベント行を更新する。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import EventRecord, EventScoreRule
from vcenter_event_assistant.rules.notable import final_notable_score


async def load_event_score_delta_map(session: AsyncSession) -> dict[str, int]:
    """``EventScoreRule`` から event_type → score_delta の辞書を読み込む。

    Args:
        session: 非同期 DB セッション。

    Returns:
        イベント種別をキー、加算 delta を値とする辞書。
    """
    res = await session.execute(select(EventScoreRule.event_type, EventScoreRule.score_delta))
    return {str(et): int(d) for et, d in res.all()}


async def recalculate_notable_scores_for_event_type(
    session: AsyncSession,
    *,
    event_type: str,
    score_delta: int,
) -> int:
    """``event_type`` に一致する全行の ``notable_score`` を再計算する。更新行数を返す。"""
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


async def recalculate_all_notable_scores(session: AsyncSession) -> int:
    """全イベント行の ``notable_score`` を現行ルールマップで再計算する。走査行数を返す。"""
    delta_map = await load_event_score_delta_map(session)
    res = await session.execute(select(EventRecord))
    rows = list(res.scalars().all())
    for row in rows:
        d = delta_map.get(row.event_type, 0)
        row.notable_score = final_notable_score(
            event_type=row.event_type,
            severity=row.severity,
            message=row.message,
            score_delta=d,
        )
    return len(rows)
