"""インシデントタイムライン専用 API。"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from contextlib import ExitStack
from datetime import datetime, timezone
from functools import partial
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Response
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
from vcenter_event_assistant.db.models import IncidentTimelineManualSnapshot, VCenter
from vcenter_event_assistant.services.incident_timeline_export import (
    DETAIL_MAX_CHARS,
    RESULT_MAX_BYTES,
    ExportFormat,
    ExportResultTooLarge,
    SavedSnapshotSource,
    generate_investigation_export,
)
from vcenter_event_assistant.services.incident_timeline_view import (
    build_incident_timeline_view,
    timeline_aggregation_slot,
)

router = APIRouter(prefix="/incident-timeline", tags=["incident-timeline"])
logger = logging.getLogger(__name__)

# 保存する結果の各行の detail の文字数の上限（超えたら切って印を付ける。保存用のコピーだけに適用する）。
SNAPSHOT_DETAIL_MAX_CHARS = DETAIL_MAX_CHARS
_DETAIL_CUT_MARK = "…（保存時に切り詰めました）"
# 保存する結果の JSON（UTF-8）のバイト数の上限。超えたら保存せず 413 にする。
MAX_SNAPSHOT_RESULT_BYTES = RESULT_MAX_BYTES


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
        except ValidationError as exc:
            # 入力値はログに出さない。どの項目がなぜ読めないかだけを残す。
            reasons = [(e["loc"], e["type"]) for e in exc.errors(include_input=False, include_url=False)]
            logger.warning(
                "snapshot %s has an unreadable build_request_payload; falling back to the stored range: %s",
                snapshot.id,
                reasons,
            )
    return IncidentTimelineBuildRequest(
        from_time=_normalize_utc_datetime(snapshot.from_time),
        to_time=_normalize_utc_datetime(snapshot.to_time),
    )


def _graph_context_for_response(snapshot: IncidentTimelineManualSnapshot) -> IncidentTimelineGraphContext | None:
    """保存したグラフ再生用メタ。読めないとき（UTC に直せない日時を含む古い行など）は None（一覧・詳細を壊さない）。"""
    raw = snapshot.graph_context
    if not raw:
        return None
    try:
        return IncidentTimelineGraphContext.model_validate(raw)
    except ValidationError as exc:
        # 入力値はログに出さない。どの項目がなぜ読めないかだけを残す。
        reasons = [(e["loc"], e["type"]) for e in exc.errors(include_input=False, include_url=False)]
        logger.warning("snapshot %s has an unreadable graph_context: %s", snapshot.id, reasons)
        return None


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


def _export_time_zone(time_zone: str) -> ZoneInfo:
    try:
        return ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="time_zone に有効な IANA タイムゾーン名を指定してください",
        ) from None


async def _run_export(
    slot: ExitStack,
    generate: Callable[[], tuple[str, bytes]],
    export_format: ExportFormat,
    source: str,
) -> Response:
    worker = asyncio.create_task(asyncio.to_thread(generate))
    try:
        filename, content = await asyncio.shield(worker)
    except asyncio.CancelledError:
        # 要求が取り消されてもスレッドは走り続けるので、生成が終わるまで枠を返さない。
        held_slot = slot.pop_all()

        def release_when_done(done: asyncio.Task[tuple[str, bytes]]) -> None:
            held_slot.close()
            if not done.cancelled():
                done.exception()

        worker.add_done_callback(release_when_done)
        raise
    except ExportResultTooLarge:
        raise HTTPException(
            status_code=413,
            detail="出力する結果が大きすぎます。期間を狭めるか、種別を減らしてください",
        ) from None
    logger.info(
        "Incident timeline export: source=%s format=%s bytes=%d",
        source,
        export_format,
        len(content),
    )
    return Response(
        content,
        media_type="text/markdown; charset=utf-8"
        if export_format == "md"
        else "application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/export", dependencies=[RequireViewer], response_class=Response)
async def post_incident_timeline_export(
    body: IncidentTimelineViewRequest,
    format: ExportFormat,
    time_zone: str = Query(default="UTC", max_length=128),
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_current_principal),
) -> Response:
    zone = _export_time_zone(time_zone)
    owner_key = principal_owner_key(principal)
    result = await build_incident_timeline_view(session, body, owner_key=owner_key)
    aggregated_at = datetime.now(timezone.utc)
    # 集計が枠を返してから生成用に取り直す。間に await を入れない。
    # 入れると、集計を終えた後に 503 になる窓ができる。
    with ExitStack() as slot:
        slot.enter_context(timeline_aggregation_slot(owner_key))
        vcenter_name = None
        if body.vcenter_id is not None:
            vcenter_name = await session.scalar(
                select(VCenter.name).where(VCenter.id == body.vcenter_id)
            )
        return await _run_export(
            slot,
            partial(
                generate_investigation_export,
                result,
                body,
                format,
                zone,
                datetime.now(timezone.utc),
                aggregated_at=aggregated_at,
                current_vcenter_name=vcenter_name,
            ),
            format,
            "current",
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
    row = await _get_snapshot(session, _parse_snapshot_id(snapshot_id))
    # 保存時のスキーマで読めない結果は「結果なし」として返し、画面が再集計に落ちられるようにする。
    result = _result_for_response(row)
    base = _list_item(row, has_result=result is not None)
    return IncidentTimelineManualSnapshotDetail(**base.model_dump(), result=result)


def _parse_snapshot_id(snapshot_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(snapshot_id)
    except ValueError:
        raise HTTPException(
            status_code=404, detail="スナップショットが見つかりません"
        ) from None


async def _get_snapshot(
    session: AsyncSession, snapshot_id: uuid.UUID
) -> IncidentTimelineManualSnapshot:
    row = await session.get(IncidentTimelineManualSnapshot, snapshot_id)
    if row is None:
        raise HTTPException(status_code=404, detail="スナップショットが見つかりません")
    return row


def _generate_saved_export(
    row: IncidentTimelineManualSnapshot,
    export_format: ExportFormat,
    zone: ZoneInfo,
    exported_at: datetime,
) -> tuple[str, bytes]:
    """保存した結果を読み、再集計せずに資料を作る。"""
    result = _result_for_response(row) if row.snapshot_kind == "manual" else None
    if result is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "結果が保存されていません。開いて再集計してから、今の表示を出力してください。"
                "元データの保持期間（既定 7 日）を過ぎていると、再集計の結果は空か一部になります"
            ),
            headers={"X-VEA-Error-Code": "snapshot_result_missing"},
        )
    snapshot = SavedSnapshotSource(
        row.id, row.created_at or row.timestamp_utc, row.operator_note
    )
    return generate_investigation_export(
        result,
        _view_request_for_response(row),
        export_format,
        zone,
        exported_at,
        snapshot=snapshot,
    )


@router.get(
    "/snapshots/manual/{id}/export",
    dependencies=[RequireViewer],
    response_class=Response,
)
async def get_manual_snapshot_export(
    id: str,
    format: ExportFormat,
    time_zone: str = Query(default="UTC", max_length=128),
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_current_principal),
) -> Response:
    zone = _export_time_zone(time_zone)
    snapshot_id = _parse_snapshot_id(id)
    with ExitStack() as slot:
        slot.enter_context(timeline_aggregation_slot(principal_owner_key(principal)))
        row = await _get_snapshot(session, snapshot_id)
        # 要求の終了でセッションが閉じても、読み込んだ列をスレッドから参照できるようにする。
        session.expunge(row)
        return await _run_export(
            slot,
            partial(
                _generate_saved_export, row, format, zone, datetime.now(timezone.utc)
            ),
            format,
            str(row.id),
        )
