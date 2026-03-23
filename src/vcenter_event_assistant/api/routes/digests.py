"""ダイジェスト一覧・実行 API。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.datetime_utils import to_utc
from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas import DigestListResponse, DigestRead, DigestRunRequest
from vcenter_event_assistant.db.models import DigestRecord
from vcenter_event_assistant.services.digest_run import run_digest_once
from vcenter_event_assistant.services.digest_window import utc_yesterday_window
from vcenter_event_assistant.settings import get_settings

router = APIRouter(prefix="/digests", tags=["digests"])


@router.get("", response_model=DigestListResponse)
async def list_digests(
    session: AsyncSession = Depends(get_session),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DigestListResponse:
    count_q = select(func.count()).select_from(DigestRecord)
    total = int((await session.execute(count_q)).scalar_one() or 0)

    q = (
        select(DigestRecord)
        .order_by(DigestRecord.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    res = await session.execute(q)
    rows = list(res.scalars().all())
    return DigestListResponse(items=[DigestRead.model_validate(r) for r in rows], total=total)


@router.get("/{digest_id}", response_model=DigestRead)
async def get_digest(digest_id: int, session: AsyncSession = Depends(get_session)) -> DigestRead:
    row = await session.get(DigestRecord, digest_id)
    if row is None:
        raise HTTPException(status_code=404, detail="digest not found")
    return DigestRead.model_validate(row)


@router.post("/run", response_model=DigestRead)
async def run_digest(
    body: DigestRunRequest = Body(default_factory=DigestRunRequest),
    session: AsyncSession = Depends(get_session),
) -> DigestRead:
    req = body
    if req.from_time is not None and req.to_time is not None:
        period_start = to_utc(req.from_time)
        period_end = to_utc(req.to_time)
    else:
        period_start, period_end = utc_yesterday_window()
    row = await run_digest_once(
        session,
        kind=req.kind,
        from_utc=period_start,
        to_utc=period_end,
        settings=get_settings(),
    )
    return DigestRead.model_validate(row)
