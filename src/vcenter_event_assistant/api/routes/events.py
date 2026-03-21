"""Event listing API."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas import EventRead
from vcenter_event_assistant.auth.dependencies import require_auth
from vcenter_event_assistant.db.models import EventRecord

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventRead])
async def list_events(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth),
    vcenter_id: uuid.UUID | None = None,
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    min_score: int | None = Query(default=None, ge=0, le=100),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[EventRecord]:
    q = select(EventRecord)
    if vcenter_id is not None:
        q = q.where(EventRecord.vcenter_id == vcenter_id)
    if from_time is not None:
        q = q.where(EventRecord.occurred_at >= from_time)
    if to_time is not None:
        q = q.where(EventRecord.occurred_at <= to_time)
    if min_score is not None:
        q = q.where(EventRecord.notable_score >= min_score)
    q = q.order_by(EventRecord.occurred_at.desc()).offset(offset).limit(limit)
    res = await session.execute(q)
    return list(res.scalars().all())
