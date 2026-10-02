"""Log search, independent from event scoring and alerts."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.datetime_utils import to_utc
from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.routes.events import _contains_case_insensitive
from vcenter_event_assistant.api.schemas.logs import LogListResponse, LogRead
from vcenter_event_assistant.db.models import LogRecord

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("", response_model=LogListResponse)
async def list_logs(
    session: AsyncSession = Depends(get_session),
    vcenter_id: UUID | None = None,
    source_id: str | None = Query(default=None, max_length=128),
    log_kind: str | None = Query(default=None, max_length=64),
    severity: str | None = Query(default=None, max_length=64),
    message_contains: str | None = Query(default=None, max_length=1000),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> LogListResponse:
    if (
        from_time is not None
        and to_time is not None
        and to_utc(from_time) > to_utc(to_time)
    ):
        raise HTTPException(status_code=400, detail="from must be before to")
    conditions = []
    for column, value in (
        (LogRecord.vcenter_id, vcenter_id),
        (LogRecord.source_id, source_id),
        (LogRecord.log_kind, log_kind),
        (LogRecord.severity, severity),
    ):
        if value is not None:
            conditions.append(column == value)
    if from_time is not None:
        conditions.append(LogRecord.effective_at >= to_utc(from_time))
    if to_time is not None:
        conditions.append(LogRecord.effective_at <= to_utc(to_time))
    if message_contains and message_contains.strip():
        conditions.append(
            _contains_case_insensitive(LogRecord.message, message_contains.strip())
        )
    total = (
        await session.execute(
            select(func.count()).select_from(LogRecord).where(*conditions)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(LogRecord)
            .where(*conditions)
            .order_by(LogRecord.effective_at.desc(), LogRecord.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars()
    return LogListResponse(items=[LogRead.model_validate(r) for r in rows], total=total)
