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
from vcenter_event_assistant.services.digest_timezone import resolve_digest_timezone
from vcenter_event_assistant.services.digest_window import (
    zoned_previous_calendar_month_window,
    zoned_previous_week_window,
    zoned_yesterday_window,
)
from vcenter_event_assistant.settings import get_settings

router = APIRouter(prefix="/digests", tags=["digests"])

_DEFAULT_WINDOW_KINDS = frozenset({"daily", "weekly", "monthly"})


def _canonical_digest_kind(raw: str) -> str:
    """
    既知の ``kind`` は小文字に正規化する（``_load_template_source`` の ``weekly`` / ``monthly`` 判定と一致させる）。

    それ以外の文字列は前後空白のみ除去し、大文字小文字は保持する。
    """
    stripped = raw.strip()
    key = stripped.lower()
    if key in _DEFAULT_WINDOW_KINDS:
        return key
    return stripped


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
    kind_arg = _canonical_digest_kind(req.kind)
    if req.from_time is not None and req.to_time is not None:
        period_start = to_utc(req.from_time)
        period_end = to_utc(req.to_time)
    else:
        if kind_arg not in _DEFAULT_WINDOW_KINDS:
            raise HTTPException(
                status_code=400,
                detail=(
                    "digest kind must be one of daily, weekly, monthly when from_time and to_time are omitted; "
                    f"got {req.kind!r}"
                ),
            )
        settings = get_settings()
        tz, _ = resolve_digest_timezone(settings)
        if kind_arg == "daily":
            period_start, period_end = zoned_yesterday_window(None, tz)
        elif kind_arg == "weekly":
            period_start, period_end = zoned_previous_week_window(None, tz)
        else:
            period_start, period_end = zoned_previous_calendar_month_window(None, tz)
    row = await run_digest_once(
        session,
        kind=kind_arg,
        from_utc=period_start,
        to_utc=period_end,
        settings=get_settings(),
    )
    return DigestRead.model_validate(row)
