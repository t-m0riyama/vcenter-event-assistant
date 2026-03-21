"""Event listing API."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas import EventListResponse, EventRead, EventUserCommentPatch
from vcenter_event_assistant.auth.dependencies import require_auth
from vcenter_event_assistant.db.models import EventRecord

router = APIRouter(prefix="/events", tags=["events"])


def _strip_query(s: str | None) -> str | None:
    if s is None:
        return None
    t = s.strip()
    return t if t else None


def _escape_like_metachars(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _contains_case_insensitive(column: ColumnElement[str | None], needle: str) -> ColumnElement[bool]:
    """Substring match, case-insensitive; works on SQLite and PostgreSQL via ``ilike`` + escape."""
    hay = func.coalesce(column, literal(""))
    return hay.ilike(f"%{_escape_like_metachars(needle)}%", escape="\\")


@router.get("", response_model=EventListResponse)
async def list_events(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth),
    vcenter_id: uuid.UUID | None = None,
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    min_score: int | None = Query(default=None, ge=0, le=100),
    event_type_contains: str | None = Query(default=None),
    severity_contains: str | None = Query(default=None),
    message_contains: str | None = Query(default=None),
    comment_contains: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> EventListResponse:
    conditions = []
    if vcenter_id is not None:
        conditions.append(EventRecord.vcenter_id == vcenter_id)
    if from_time is not None:
        conditions.append(EventRecord.occurred_at >= from_time)
    if to_time is not None:
        conditions.append(EventRecord.occurred_at <= to_time)
    if min_score is not None:
        conditions.append(EventRecord.notable_score >= min_score)

    et = _strip_query(event_type_contains)
    if et is not None:
        conditions.append(_contains_case_insensitive(EventRecord.event_type, et))
    sv = _strip_query(severity_contains)
    if sv is not None:
        conditions.append(_contains_case_insensitive(EventRecord.severity, sv))
    msg = _strip_query(message_contains)
    if msg is not None:
        conditions.append(_contains_case_insensitive(EventRecord.message, msg))
    cm = _strip_query(comment_contains)
    if cm is not None:
        conditions.append(_contains_case_insensitive(EventRecord.user_comment, cm))

    count_q = select(func.count()).select_from(EventRecord)
    if conditions:
        count_q = count_q.where(*conditions)
    total = int((await session.execute(count_q)).scalar_one() or 0)

    q = select(EventRecord)
    if conditions:
        q = q.where(*conditions)
    q = q.order_by(EventRecord.occurred_at.desc()).offset(offset).limit(limit)
    res = await session.execute(q)
    rows = list(res.scalars().all())
    return EventListResponse(
        items=[EventRead.model_validate(r) for r in rows],
        total=total,
    )


@router.patch("/{event_id}", response_model=EventRead)
async def patch_event_comment(
    event_id: int,
    body: EventUserCommentPatch,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth),
) -> EventRead:
    row = await session.get(EventRecord, event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="event not found")
    row.user_comment = body.user_comment
    await session.commit()
    await session.refresh(row)
    return EventRead.model_validate(row)
