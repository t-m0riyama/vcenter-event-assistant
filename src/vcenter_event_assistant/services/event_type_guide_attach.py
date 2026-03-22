"""イベント行に種別ガイド（type_guide）を付与する。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.schemas import EventRead, EventTypeGuideSnippet
from vcenter_event_assistant.db.models import EventRecord, EventTypeGuide


async def attach_type_guides_to_event_reads(
    session: AsyncSession,
    rows: list[EventRecord],
) -> list[EventRead]:
    """
    ``EventRecord`` のリストを ``EventRead`` に変換し、同一 ``event_type`` のガイドを付与する。

    イベント一覧・ダッシュボード要注意一覧で共通利用する。
    """
    types = {r.event_type for r in rows}
    guides_by_type: dict[str, EventTypeGuide] = {}
    if types:
        gr = await session.execute(select(EventTypeGuide).where(EventTypeGuide.event_type.in_(types)))
        for g in gr.scalars().all():
            guides_by_type[g.event_type] = g

    out: list[EventRead] = []
    for r in rows:
        base = EventRead.model_validate(r)
        guide = guides_by_type.get(r.event_type)
        if guide is None:
            out.append(base)
            continue
        out.append(
            base.model_copy(
                update={
                    "type_guide": EventTypeGuideSnippet(
                        general_meaning=guide.general_meaning,
                        typical_causes=guide.typical_causes,
                        remediation=guide.remediation,
                        action_required=guide.action_required,
                    ),
                },
            )
        )
    return out
