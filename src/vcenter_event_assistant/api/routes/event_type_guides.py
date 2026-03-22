"""CRUD for per-event-type guide text (meaning, causes, remediation)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas import (
    EventTypeGuideCreate,
    EventTypeGuideRead,
    EventTypeGuidesImportRequest,
    EventTypeGuidesImportResponse,
    EventTypeGuideUpdate,
)
from vcenter_event_assistant.db.models import EventTypeGuide

router = APIRouter(prefix="/event-type-guides", tags=["event-type-guides"])


@router.get("", response_model=list[EventTypeGuideRead])
async def list_event_type_guides(
    session: AsyncSession = Depends(get_session),
) -> list[EventTypeGuide]:
    res = await session.execute(select(EventTypeGuide).order_by(EventTypeGuide.event_type.asc()))
    return list(res.scalars().all())


@router.post("", response_model=EventTypeGuideRead, status_code=status.HTTP_201_CREATED)
async def create_event_type_guide(
    body: EventTypeGuideCreate,
    session: AsyncSession = Depends(get_session),
) -> EventTypeGuide:
    if not body.event_type.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="event_type is required")
    dup = await session.execute(select(EventTypeGuide.id).where(EventTypeGuide.event_type == body.event_type))
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="guide for this event_type already exists",
        )
    row = EventTypeGuide(
        event_type=body.event_type,
        general_meaning=body.general_meaning,
        typical_causes=body.typical_causes,
        remediation=body.remediation,
        action_required=body.action_required,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


@router.post("/import", response_model=EventTypeGuidesImportResponse)
async def import_event_type_guides(
    body: EventTypeGuidesImportRequest,
    session: AsyncSession = Depends(get_session),
) -> EventTypeGuidesImportResponse:
    """ガイドを一括適用する。イベント行の再計算は行わない。"""
    types_in_file = [g.event_type for g in body.guides]
    if len(types_in_file) != len(set(types_in_file)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="duplicate event_type in guides",
        )

    for g in body.guides:
        res = await session.execute(select(EventTypeGuide).where(EventTypeGuide.event_type == g.event_type))
        existing = res.scalar_one_or_none()
        if existing is None:
            session.add(
                EventTypeGuide(
                    event_type=g.event_type,
                    general_meaning=g.general_meaning,
                    typical_causes=g.typical_causes,
                    remediation=g.remediation,
                    action_required=g.action_required,
                ),
            )
        elif body.overwrite_existing:
            existing.general_meaning = g.general_meaning
            existing.typical_causes = g.typical_causes
            existing.remediation = g.remediation
            existing.action_required = g.action_required

    if body.delete_guides_not_in_import:
        s = set(types_in_file)
        if not s:
            await session.execute(delete(EventTypeGuide))
        else:
            await session.execute(delete(EventTypeGuide).where(~EventTypeGuide.event_type.in_(sorted(s))))

    await session.flush()

    cnt_res = await session.execute(select(EventTypeGuide.id))
    guides_count = len(list(cnt_res.scalars().all()))

    return EventTypeGuidesImportResponse(guides_count=guides_count)


@router.patch("/{guide_id}", response_model=EventTypeGuideRead)
async def patch_event_type_guide(
    guide_id: int,
    body: EventTypeGuideUpdate,
    session: AsyncSession = Depends(get_session),
) -> EventTypeGuide:
    row = await session.get(EventTypeGuide, guide_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="guide not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)
    await session.flush()
    await session.refresh(row)
    return row


@router.delete("/{guide_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event_type_guide(
    guide_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await session.get(EventTypeGuide, guide_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="guide not found")
    await session.delete(row)
    await session.flush()
