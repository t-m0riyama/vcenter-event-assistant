"""Metric time series API."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas import MetricPoint, MetricSeriesResponse
from vcenter_event_assistant.auth.dependencies import require_auth
from vcenter_event_assistant.db.models import MetricSample

router = APIRouter(prefix="/metrics", tags=["metrics"])


def _metric_filter_clauses(
    *,
    metric_key: str,
    vcenter_id: uuid.UUID | None,
    from_time: datetime | None,
    to_time: datetime | None,
    entity_moid: str | None,
) -> list:
    clauses = [MetricSample.metric_key == metric_key]
    if vcenter_id is not None:
        clauses.append(MetricSample.vcenter_id == vcenter_id)
    if from_time is not None:
        clauses.append(MetricSample.sampled_at >= from_time)
    if to_time is not None:
        clauses.append(MetricSample.sampled_at <= to_time)
    if entity_moid is not None:
        clauses.append(MetricSample.entity_moid == entity_moid)
    return clauses


@router.get("", response_model=MetricSeriesResponse)
async def list_metrics(
    response: Response,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_auth),
    vcenter_id: uuid.UUID | None = None,
    metric_key: str = Query(..., min_length=1, max_length=256),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    entity_moid: str | None = None,
    limit: int = Query(default=2000, ge=1, le=10000),
) -> MetricSeriesResponse:
    clauses = _metric_filter_clauses(
        metric_key=metric_key,
        vcenter_id=vcenter_id,
        from_time=from_time,
        to_time=to_time,
        entity_moid=entity_moid,
    )

    count_q = select(func.count()).select_from(MetricSample).where(*clauses)
    total = int((await session.execute(count_q)).scalar_one() or 0)

    q = (
        select(MetricSample)
        .where(*clauses)
        .order_by(MetricSample.sampled_at.asc())
        .limit(limit)
    )
    res = await session.execute(q)
    rows = list(res.scalars().all())
    points = [
        MetricPoint(
            sampled_at=r.sampled_at,
            value=r.value,
            entity_name=r.entity_name,
            entity_moid=r.entity_moid,
            metric_key=r.metric_key,
            vcenter_id=r.vcenter_id,
        )
        for r in rows
    ]
    response.headers["X-Total-Count"] = str(total)
    return MetricSeriesResponse(points=points, total=total)
