"""インシデントタイムライン専用 API。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas.chat import (
    IncidentTimelineBuildRequest,
    IncidentTimelineGraphContext,
    IncidentTimelineManualSnapshotCreateRequest,
    IncidentTimelineManualSnapshotCreateResponse,
    IncidentTimelineManualSnapshotListItem,
    IncidentTimelineManualSnapshotListResponse,
)
from vcenter_event_assistant.db.models import IncidentTimelineManualSnapshot
from vcenter_event_assistant.services.chat_context_payloads import build_incident_timeline_payload
from vcenter_event_assistant.services.chat_incident_timeline import IncidentTimelinePayload

router = APIRouter(prefix="/incident-timeline", tags=["incident-timeline"])


def _normalize_utc_datetime(value: datetime) -> datetime:
    """SQLite 等で tzinfo が落ちた日時を UTC として補正する。"""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _build_request_payload_for_response(snapshot: IncidentTimelineManualSnapshot) -> IncidentTimelineBuildRequest:
    if snapshot.build_request_payload:
        return IncidentTimelineBuildRequest.model_validate(snapshot.build_request_payload)
    return IncidentTimelineBuildRequest(
        from_time=_normalize_utc_datetime(snapshot.from_time),
        to_time=_normalize_utc_datetime(snapshot.to_time),
    )


def _graph_context_for_response(snapshot: IncidentTimelineManualSnapshot) -> IncidentTimelineGraphContext | None:
    raw = snapshot.graph_context
    if not raw:
        return None
    return IncidentTimelineGraphContext.model_validate(raw)


@router.post("", response_model=IncidentTimelinePayload)
async def post_incident_timeline(
    body: IncidentTimelineBuildRequest,
    session: AsyncSession = Depends(get_session),
) -> IncidentTimelinePayload:
    return await build_incident_timeline_payload(session, body)


@router.post("/snapshots/manual", response_model=IncidentTimelineManualSnapshotCreateResponse, status_code=201)
async def post_manual_snapshot(
    body: IncidentTimelineManualSnapshotCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> IncidentTimelineManualSnapshotCreateResponse:
    build_request_payload = body.build_request_payload or IncidentTimelineBuildRequest(
        from_time=body.from_time,
        to_time=body.to_time,
    )
    graph_context_dict: dict[str, object] | None = None
    if body.graph_context is not None:
        graph_context_dict = body.graph_context.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        )
    snapshot = IncidentTimelineManualSnapshot(
        from_time=body.from_time,
        to_time=body.to_time,
        timestamp_utc=body.timestamp_utc,
        operator_note=body.operator_note,
        build_request_payload=build_request_payload.model_dump(mode="json", by_alias=True, exclude_none=True),
        graph_context=graph_context_dict,
    )
    session.add(snapshot)
    await session.commit()
    return IncidentTimelineManualSnapshotCreateResponse(
        snapshot_id=str(snapshot.id),
        operator_note=snapshot.operator_note,
        timestamp_utc=_normalize_utc_datetime(snapshot.timestamp_utc),
        build_request_payload=_build_request_payload_for_response(snapshot),
        snapshot_kind=snapshot.snapshot_kind,
        trigger_id=snapshot.trigger_id,
        graph_context=_graph_context_for_response(snapshot),
    )


@router.get("/snapshots/manual", response_model=IncidentTimelineManualSnapshotListResponse)
async def get_manual_snapshots(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> IncidentTimelineManualSnapshotListResponse:
    total_result = await session.execute(select(func.count()).select_from(IncidentTimelineManualSnapshot))
    total = int(total_result.scalar_one())

    result = await session.execute(
        select(IncidentTimelineManualSnapshot)
        .order_by(IncidentTimelineManualSnapshot.timestamp_utc.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.scalars().all()
    items = [
        IncidentTimelineManualSnapshotListItem(
            snapshot_id=str(row.id),
            from_time=_normalize_utc_datetime(row.from_time),
            to_time=_normalize_utc_datetime(row.to_time),
            operator_note=row.operator_note,
            timestamp_utc=_normalize_utc_datetime(row.timestamp_utc),
            build_request_payload=_build_request_payload_for_response(row),
            snapshot_kind=row.snapshot_kind,
            trigger_id=row.trigger_id,
            trigger_evidence=row.trigger_evidence,
            graph_context=_graph_context_for_response(row),
        )
        for row in rows
    ]
    return IncidentTimelineManualSnapshotListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )
