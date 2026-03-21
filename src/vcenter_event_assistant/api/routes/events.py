"""Event listing API."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Integer, cast, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas import (
    EventListResponse,
    EventRateBucket,
    EventRateSeriesResponse,
    EventRead,
    EventTypesResponse,
    EventUserCommentPatch,
)
from vcenter_event_assistant.db.models import EventRecord
from vcenter_event_assistant.settings import get_settings

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


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _epoch_seconds_expr(dialect_name: str):
    """Portable UTC epoch seconds (integer) from ``occurred_at`` for bucketing."""
    if dialect_name == "postgresql":
        return cast(func.floor(func.extract("epoch", EventRecord.occurred_at)), Integer)
    return cast(func.strftime("%s", EventRecord.occurred_at), Integer)


@router.get("/event-types", response_model=EventTypesResponse)
async def list_event_types(
    session: AsyncSession = Depends(get_session),
    vcenter_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> EventTypesResponse:
    conditions: list[ColumnElement[bool]] = []
    if vcenter_id is not None:
        conditions.append(EventRecord.vcenter_id == vcenter_id)
    q = select(EventRecord.event_type).group_by(EventRecord.event_type).order_by(
        func.max(EventRecord.occurred_at).desc()
    )
    if conditions:
        q = q.where(*conditions)
    q = q.limit(limit)
    res = await session.execute(q)
    types = [str(r[0]) for r in res.all()]
    return EventTypesResponse(event_types=types)


@router.get("/rate-series", response_model=EventRateSeriesResponse)
async def event_rate_series(
    session: AsyncSession = Depends(get_session),
    event_type: str = Query(..., min_length=1, max_length=512),
    from_time: datetime = Query(..., alias="from"),
    to_time: datetime = Query(..., alias="to"),
    bucket_seconds: int | None = Query(default=None, ge=60, le=86400),
    vcenter_id: uuid.UUID | None = None,
) -> EventRateSeriesResponse:
    ft = _to_utc(from_time)
    tt = _to_utc(to_time)
    if ft >= tt:
        raise HTTPException(status_code=400, detail="from must be before to")

    b = bucket_seconds if bucket_seconds is not None else get_settings().perf_sample_interval_seconds

    conditions: list[ColumnElement[bool]] = [
        EventRecord.event_type == event_type.strip(),
        EventRecord.occurred_at >= ft,
        EventRecord.occurred_at <= tt,
    ]
    if vcenter_id is not None:
        conditions.append(EventRecord.vcenter_id == vcenter_id)

    bind = session.get_bind()
    dialect_name = bind.dialect.name if bind is not None else "sqlite"
    epoch_sec = _epoch_seconds_expr(dialect_name)
    bucket_epoch = epoch_sec - func.mod(epoch_sec, literal(b))

    q = (
        select(bucket_epoch.label("bucket_epoch"), func.count().label("cnt"))
        .where(*conditions)
        .group_by(bucket_epoch)
    )
    res = await session.execute(q)
    count_by_epoch: dict[int, int] = {}
    for row in res.all():
        be = int(row.bucket_epoch)
        count_by_epoch[be] = int(row.cnt)

    from_ts = int(ft.timestamp())
    to_ts = int(tt.timestamp())
    first = (from_ts // b) * b
    last = (to_ts // b) * b
    buckets: list[EventRateBucket] = []
    for s in range(first, last + b, b):
        dt = datetime.fromtimestamp(s, tz=timezone.utc)
        buckets.append(EventRateBucket(bucket_start=dt, count=count_by_epoch.get(s, 0)))

    return EventRateSeriesResponse(bucket_seconds=b, buckets=buckets)


@router.get("", response_model=EventListResponse)
async def list_events(
    session: AsyncSession = Depends(get_session),
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
) -> EventRead:
    row = await session.get(EventRecord, event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="event not found")
    row.user_comment = body.user_comment
    await session.flush()
    await session.refresh(row)
    return EventRead.model_validate(row)
