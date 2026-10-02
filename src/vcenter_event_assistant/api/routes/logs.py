"""Log search, independent from event scoring and alerts."""

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.datetime_utils import to_utc
from vcenter_event_assistant.api.deps import get_app_settings, get_session
from vcenter_event_assistant.api.routes.events import _contains_case_insensitive
from vcenter_event_assistant.api.schemas.logs import LogListResponse, LogRead
from vcenter_event_assistant.db.models import LogRecord
from vcenter_event_assistant.db.session import get_session_factory
from vcenter_event_assistant.settings import Settings
from vcenter_event_assistant.services.log_export import (
    prepare_log_export,
    stream_log_csv,
)

router = APIRouter(prefix="/logs", tags=["logs"])


def log_conditions(
    vcenter_id: UUID | None = None,
    source_id: str | None = Query(default=None, max_length=128),
    log_kind: str | None = Query(default=None, max_length=64),
    severity: str | None = Query(default=None, max_length=64),
    message_contains: str | None = Query(default=None, max_length=1000),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
) -> list:
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
    return conditions


@router.get("", response_model=LogListResponse)
async def list_logs(
    session: AsyncSession = Depends(get_session),
    conditions: list = Depends(log_conditions),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> LogListResponse:
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


@router.get("/export.csv", response_class=StreamingResponse)
async def export_logs(
    request: Request,
    conditions: list = Depends(log_conditions),
    settings: Settings = Depends(get_app_settings),
    time_zone: str = Query(default="UTC", max_length=128),
) -> StreamingResponse:
    try:
        zone = ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid time_zone") from None
    factory = get_session_factory(settings=settings)
    # Validate the first DB read before sending a successful response.
    upper_id, first_batch = await prepare_log_export(factory, conditions)
    filename = f"logs-{datetime.now(zone):%Y%m%d-%H%M%S}.csv"
    return StreamingResponse(
        stream_log_csv(factory, conditions, zone, upper_id, first_batch, request),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )
