"""インシデントタイムライン専用 API。"""

from __future__ import annotations

from datetime import datetime, timezone

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import defer
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.auth_deps import (
    Principal,
    RequireOperator,
    RequireViewer,
    get_current_principal,
    principal_owner_key,
)
from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas.chat import (
    IncidentTimelineBuildRequest,
    IncidentTimelineGraphContext,
    IncidentTimelineManualSnapshotCreateRequest,
    IncidentTimelineManualSnapshotCreateResponse,
    IncidentTimelineManualSnapshotDetail,
    IncidentTimelineManualSnapshotListItem,
    IncidentTimelineManualSnapshotListResponse,
)
from vcenter_event_assistant.api.schemas.incident_timeline_view import (
    IncidentTimelineSavedViewRequest,
    IncidentTimelineViewRequest,
    IncidentTimelineViewResponse,
)
from vcenter_event_assistant.db.models import IncidentTimelineManualSnapshot
from vcenter_event_assistant.services.incident_timeline_view import build_incident_timeline_view

router = APIRouter(prefix="/incident-timeline", tags=["incident-timeline"])
logger = logging.getLogger(__name__)

# 保存する結果の各行の detail の文字数の上限（超えたら切って印を付ける。保存用のコピーだけに適用する）。
SNAPSHOT_DETAIL_MAX_CHARS = 2000
_DETAIL_CUT_MARK = "…（保存時に切り詰めました）"
# 保存する結果の JSON（UTF-8）のバイト数の上限。超えたら保存せず 413 にする。
MAX_SNAPSHOT_RESULT_BYTES = 8 * 1024 * 1024


def _truncate_details_for_storage(value: object) -> object:
    """結果の中の ``detail``（文字列）をすべて上限で切る。行・``highlights.first_signal`` など同じ形の場所に効く。"""
    if isinstance(value, dict):
        return {
            key: (
                item[:SNAPSHOT_DETAIL_MAX_CHARS] + _DETAIL_CUT_MARK
                if key == "detail" and isinstance(item, str) and len(item) > SNAPSHOT_DETAIL_MAX_CHARS
                else _truncate_details_for_storage(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_truncate_details_for_storage(item) for item in value]
    return value


def _json_utf8_size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def _normalize_utc_datetime(value: datetime) -> datetime:
    """SQLite 等で tzinfo が落ちた日時を UTC として補正する。"""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _build_request_payload_for_response(snapshot: IncidentTimelineManualSnapshot) -> IncidentTimelineBuildRequest:
    """保存した条件。読めないとき（UTC に直せない日時を含む古い行など）は列の期間から作る（一覧・詳細を壊さない）。

    列の期間から作ると ``vcenter_id`` など保存した他の項目は失われるが、読めない行なので許容する。
    """
    if snapshot.build_request_payload:
        try:
            return IncidentTimelineBuildRequest.model_validate(snapshot.build_request_payload)
        except ValidationError:
            logger.warning("snapshot %s has an unreadable build_request_payload", snapshot.id)
    return IncidentTimelineBuildRequest(
        from_time=_normalize_utc_datetime(snapshot.from_time),
        to_time=_normalize_utc_datetime(snapshot.to_time),
    )


def _graph_context_for_response(snapshot: IncidentTimelineManualSnapshot) -> IncidentTimelineGraphContext | None:
    raw = snapshot.graph_context
    if not raw:
        return None
    return IncidentTimelineGraphContext.model_validate(raw)


def _view_request_for_response(snapshot: IncidentTimelineManualSnapshot) -> IncidentTimelineSavedViewRequest | None:
    """保存した view のリクエスト。将来スキーマが変わって読めないときは None（一覧・詳細を壊さない）。"""
    raw = snapshot.view_request_payload
    if not raw:
        return None
    try:
        return IncidentTimelineSavedViewRequest.model_validate(raw)
    except ValidationError:
        logger.warning("snapshot %s has an unreadable view_request_payload", snapshot.id)
        return None


def _result_for_response(snapshot: IncidentTimelineManualSnapshot) -> IncidentTimelineViewResponse | None:
    """保存した view の結果。無い、または保存時のスキーマと合わないときは None（画面は再集計に落ちる）。"""
    raw = snapshot.result_payload
    if not raw:
        return None
    try:
        return IncidentTimelineViewResponse.model_validate(raw)
    except ValidationError:
        logger.warning("snapshot %s has a result_payload that no longer matches the schema", snapshot.id)
        return None


def _list_item(snapshot: IncidentTimelineManualSnapshot, *, has_result: bool) -> IncidentTimelineManualSnapshotListItem:
    return IncidentTimelineManualSnapshotListItem(
        snapshot_id=str(snapshot.id),
        from_time=_normalize_utc_datetime(snapshot.from_time),
        to_time=_normalize_utc_datetime(snapshot.to_time),
        operator_note=snapshot.operator_note,
        timestamp_utc=_normalize_utc_datetime(snapshot.timestamp_utc),
        build_request_payload=_build_request_payload_for_response(snapshot),
        snapshot_kind=snapshot.snapshot_kind,
        trigger_id=snapshot.trigger_id,
        trigger_evidence=snapshot.trigger_evidence,
        graph_context=_graph_context_for_response(snapshot),
        has_result=has_result,
        view_request=_view_request_for_response(snapshot),
        created_at=_normalize_utc_datetime(snapshot.created_at) if snapshot.created_at else None,
    )


@router.post("/view", dependencies=[RequireViewer], response_model=IncidentTimelineViewResponse)
async def post_incident_timeline_view(
    body: IncidentTimelineViewRequest,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_current_principal),
) -> IncidentTimelineViewResponse:
    return await build_incident_timeline_view(
        session, body, owner_key=principal_owner_key(principal)
    )


@router.post("/snapshots/manual", dependencies=[RequireOperator], response_model=IncidentTimelineManualSnapshotCreateResponse, status_code=201)
async def post_manual_snapshot(
    body: IncidentTimelineManualSnapshotCreateRequest,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_current_principal),
) -> IncidentTimelineManualSnapshotCreateResponse:
    from_time, to_time = body.from_time, body.to_time
    build_request_payload = body.build_request_payload
    view_request_payload: dict[str, object] | None = None
    result_payload: dict[str, object] | None = None
    if body.view_request is not None:
        # 結果はサーバ側で集計する。同時実行の上限（503）と行数の上限（422）は view と同じ関数の中で効き、
        # 失敗したら例外のままここを抜けるので、スナップショットは保存されない。
        result = await build_incident_timeline_view(
            session, body.view_request, owner_key=principal_owner_key(principal)
        )
        view_request_payload = body.view_request.model_dump(mode="json", by_alias=True)
        result_payload = _truncate_details_for_storage(result.model_dump(mode="json"))
        if _json_utf8_size(result_payload) > MAX_SNAPSHOT_RESULT_BYTES:
            raise HTTPException(
                status_code=413,
                detail="保存する結果が大きすぎます。期間を狭めるか、種別を減らしてからもう一度保存してください。",
            )
        from_time, to_time = body.view_request.from_time, body.view_request.to_time
        # 旧形式の表示（結果を読めないときの再集計）用に、条件を build_request_payload にも写す。
        build_request_payload = build_request_payload or IncidentTimelineBuildRequest(
            from_time=from_time,
            to_time=to_time,
            vcenter_id=body.view_request.vcenter_id,
        )
    build_request_payload = build_request_payload or IncidentTimelineBuildRequest(
        from_time=from_time,
        to_time=to_time,
    )
    graph_context_dict: dict[str, object] | None = None
    if body.graph_context is not None:
        graph_context_dict = body.graph_context.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        )
    snapshot = IncidentTimelineManualSnapshot(
        from_time=from_time,
        to_time=to_time,
        timestamp_utc=body.timestamp_utc,
        operator_note=body.operator_note,
        build_request_payload=build_request_payload.model_dump(mode="json", by_alias=True, exclude_none=True),
        graph_context=graph_context_dict,
    )
    # 無いときは属性を設定しない（None を代入すると SQL の NULL ではなく JSON の null になる）。
    if view_request_payload is not None:
        snapshot.view_request_payload = view_request_payload
        snapshot.result_payload = result_payload
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
        created_at=_normalize_utc_datetime(snapshot.created_at) if snapshot.created_at else None,
    )


@router.get("/snapshots/manual", dependencies=[RequireViewer], response_model=IncidentTimelineManualSnapshotListResponse)
async def get_manual_snapshots(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> IncidentTimelineManualSnapshotListResponse:
    total_result = await session.execute(select(func.count()).select_from(IncidentTimelineManualSnapshot))
    total = int(total_result.scalar_one())

    # 結果は大きいので読まない。has_result は NULL かどうかだけを DB で判定する。
    result = await session.execute(
        select(IncidentTimelineManualSnapshot, IncidentTimelineManualSnapshot.result_payload.is_not(None))
        .options(defer(IncidentTimelineManualSnapshot.result_payload))
        .order_by(IncidentTimelineManualSnapshot.timestamp_utc.desc())
        .limit(limit)
        .offset(offset)
    )
    items = [_list_item(row, has_result=bool(has_result)) for row, has_result in result.all()]
    return IncidentTimelineManualSnapshotListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/snapshots/manual/{snapshot_id}",
    dependencies=[RequireViewer],
    response_model=IncidentTimelineManualSnapshotDetail,
)
async def get_manual_snapshot(
    snapshot_id: str,
    session: AsyncSession = Depends(get_session),
) -> IncidentTimelineManualSnapshotDetail:
    try:
        parsed_id = uuid.UUID(snapshot_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="スナップショットが見つかりません") from None
    row = await session.get(IncidentTimelineManualSnapshot, parsed_id)
    if row is None:
        raise HTTPException(status_code=404, detail="スナップショットが見つかりません")
    # 保存時のスキーマで読めない結果は「結果なし」として返し、画面が再集計に落ちられるようにする。
    result = _result_for_response(row)
    base = _list_item(row, has_result=result is not None)
    return IncidentTimelineManualSnapshotDetail(**base.model_dump(), result=result)
