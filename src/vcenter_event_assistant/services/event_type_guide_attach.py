"""イベント行に種別ガイド（type_guide）を付与する。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from vcenter_event_assistant.api.schemas import EventRead, EventTypeCountRow, EventTypeGuideSnippet
from vcenter_event_assistant.db.models import EventRecord, EventTypeGuide
from vcenter_event_assistant.db.session import ensure_event_type_guides_action_required_column


def _is_missing_action_required_column(exc: OperationalError) -> bool:
    msg = f"{exc.orig!s} {exc!s}"
    return "action_required" in msg and "no such column" in msg


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
        try:
            gr = await session.execute(select(EventTypeGuide).where(EventTypeGuide.event_type.in_(types)))
        except OperationalError as e:
            if not _is_missing_action_required_column(e):
                raise
            bind = session.get_bind()
            if not isinstance(bind, AsyncEngine):
                raise
            await ensure_event_type_guides_action_required_column(bind)
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


async def attach_type_guides_to_event_type_count_rows(
    session: AsyncSession,
    rows: list[EventTypeCountRow],
) -> list[EventTypeCountRow]:
    """
    イベント種別集計行（ダッシュボード「種別上位」）に ``event_type`` 一致の種別ガイドを付与する。
    """
    if not rows:
        return rows
    types = {r.event_type for r in rows}
    guides_by_type: dict[str, EventTypeGuide] = {}
    if types:
        try:
            gr = await session.execute(select(EventTypeGuide).where(EventTypeGuide.event_type.in_(types)))
        except OperationalError as e:
            if not _is_missing_action_required_column(e):
                raise
            bind = session.get_bind()
            if not isinstance(bind, AsyncEngine):
                raise
            await ensure_event_type_guides_action_required_column(bind)
            gr = await session.execute(select(EventTypeGuide).where(EventTypeGuide.event_type.in_(types)))
        for g in gr.scalars().all():
            guides_by_type[g.event_type] = g

    out: list[EventTypeCountRow] = []
    for r in rows:
        guide = guides_by_type.get(r.event_type)
        if guide is None:
            out.append(r)
            continue
        out.append(
            r.model_copy(
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
