"""インシデント記録の一覧、編集と紐付けの API。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.auth_deps import (
    Principal,
    RequireAdmin,
    RequireOperator,
    RequireViewer,
    get_current_principal,
)
from vcenter_event_assistant.api.deps import get_app_settings, get_session
from vcenter_event_assistant.api.schemas.incidents import (
    CreateLinkResults,
    EntryCreate,
    EntryRead,
    IncidentCreate,
    IncidentCreateResponse,
    IncidentDetail,
    IncidentListResponse,
    IncidentPatch,
    IncidentStatus,
    LinkResponse,
    LinkResult,
    SnapshotLinksRequest,
    TimedLinksRequest,
)
from vcenter_event_assistant.auth.timeutil import utcnow
from vcenter_event_assistant.db.models import Incident, IncidentAlert, IncidentEntry, IncidentEvent, IncidentSnapshot
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.incidents import (
    LINK_NAMES,
    MAX_NOTES,
    LinkBatch,
    LinkModel,
    add_alert_links,
    add_links,
    apply_incident_patch,
    copy_event,
    fits_integer_id,
    list_incidents,
    lock_incident,
    mark_incident_updated,
    read_incident_detail,
    record_link_additions,
    reference_snapshot,
)
from vcenter_event_assistant.settings import Settings

router = APIRouter(prefix="/incidents", tags=["incidents"])


async def _incident_write_session(settings: Settings = Depends(get_app_settings)) -> AsyncIterator[AsyncSession]:
    async with session_scope(settings=settings, isolate_memory=True) as session:
        yield session


ReadSession = Annotated[AsyncSession, Depends(get_session)]
WriteSession = Annotated[AsyncSession, Depends(_incident_write_session, scope="function")]
CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]


def _parse_incident_id(id: str) -> UUID:
    try:
        return UUID(id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Incident not found") from exc


IncidentId = Annotated[UUID, Depends(_parse_incident_id)]

def _actor_name(principal: Principal) -> str:
    username = principal.username
    display_name = principal.display_name
    if display_name and display_name != username:
        # DB の列に収まる範囲で表示名を写し、利用者を区別するユーザー名を残す。
        available = 256 - len(username) - 2
        if available > 0:
            return f"{display_name[:available]}（{username}）"
    return username


@dataclass(frozen=True)
class IncidentWrite:
    id: UUID
    session: AsyncSession
    now: datetime
    actor: str


async def _lock_incident(
    incident_id: UUID, session: AsyncSession, principal: Principal, *, revision: UUID | None = None,
) -> IncidentWrite:
    if not await lock_incident(session, incident_id, revision=revision):
        if revision is None or await session.scalar(select(Incident.id).where(Incident.id == incident_id)) is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        raise HTTPException(
            status_code=409,
            detail="Incident has changed since it was read",
            headers={"X-VEA-Error-Code": "incident_stale"},
        )
    return IncidentWrite(incident_id, session, utcnow(), _actor_name(principal))


async def _locked_incident(incident_id: IncidentId, session: WriteSession, principal: CurrentPrincipal) -> IncidentWrite:
    return await _lock_incident(incident_id, session, principal)


LockedIncident = Annotated[IncidentWrite, Depends(_locked_incident)]


async def _get_incident(session: AsyncSession, id: UUID) -> Incident:
    incident = await session.get(Incident, id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.get("", dependencies=[RequireViewer])
async def get_incidents(
    session: ReadSession,
    status: Annotated[list[IncidentStatus] | None, Query()] = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> IncidentListResponse:
    page = await list_incidents(session, status if status is not None else ["open", "monitoring"], q, limit, offset)
    return IncidentListResponse.from_page(page)


@router.get("/{id}", dependencies=[RequireViewer])
async def get_incident(incident_id: IncidentId, session: ReadSession) -> IncidentDetail:
    incident = await _get_incident(session, incident_id)
    return IncidentDetail.from_details(await read_incident_detail(session, incident))


@router.post("", dependencies=[RequireOperator], status_code=201)
async def create_incident(
    body: IncidentCreate, session: WriteSession, principal: CurrentPrincipal, settings: AppSettings,
) -> IncidentCreateResponse:
    now = utcnow()
    actor = _actor_name(principal)
    incident = Incident(
        title=body.title, status=body.status, level=body.level, assignee=body.assignee,
        summary=body.summary, started_at=body.started_at, resolved_at=now if body.status == "resolved" else None,
        created_by=actor, updated_by=actor, created_at=now, updated_at=now,
    )
    session.add(incident)
    await session.flush()
    events = await add_links(session, incident.id, IncidentEvent, body.events, copy_event, actor, now)
    alerts = await add_alert_links(
        session, incident.id, body.alerts, settings.perf_sample_interval_seconds, actor, now,
    )
    snapshots = await add_links(
        session, incident.id, IncidentSnapshot, body.snapshot_ids, reference_snapshot, actor, now,
    )
    record_link_additions(
        session, incident.id, actor, now, (IncidentEvent, events), (IncidentAlert, alerts), (IncidentSnapshot, snapshots),
    )
    return IncidentCreateResponse(
        incident=IncidentDetail.from_details(await read_incident_detail(session, incident)),
        link_results=CreateLinkResults(
            events=[LinkResult.model_validate(item) for item in events.results],
            alerts=[LinkResult.model_validate(item) for item in alerts.results],
            snapshots=[LinkResult.model_validate(item) for item in snapshots.results],
        ),
    )


@router.patch("/{id}", dependencies=[RequireOperator])
async def patch_incident(
    incident_id: IncidentId, body: IncidentPatch, session: WriteSession, principal: CurrentPrincipal,
) -> IncidentDetail:
    write = await _lock_incident(incident_id, session, principal, revision=body.revision)
    incident = await _get_incident(session, write.id)
    fields = {field: getattr(body, field) for field in body.model_fields_set - {"revision"}}
    apply_incident_patch(session, incident, fields, write.now, write.actor)
    return IncidentDetail.from_details(await read_incident_detail(session, incident))


@router.delete("/{id}", dependencies=[RequireAdmin], status_code=204)
async def delete_incident(write: LockedIncident) -> None:
    await write.session.execute(delete(Incident).where(Incident.id == write.id))


@router.post("/{id}/entries", dependencies=[RequireOperator], status_code=201)
async def add_entry(body: EntryCreate, write: LockedIncident) -> EntryRead:
    count = await write.session.scalar(select(func.count()).select_from(IncidentEntry).where(
        IncidentEntry.incident_id == write.id, IncidentEntry.kind == "note",
    ))
    if count is not None and count >= MAX_NOTES:
        raise HTTPException(
            status_code=409,
            detail="メモが上限に達しました。新しいインシデントを作ってください",
            headers={"X-VEA-Error-Code": "incident_entry_limit"},
        )
    entry = IncidentEntry(
        incident_id=write.id, kind="note", body=body.body, created_at=write.now, author=write.actor,
    )
    write.session.add(entry)
    await mark_incident_updated(write.session, write.id, write.now, write.actor)
    await write.session.flush()
    return EntryRead.model_validate(entry)


@router.delete("/{id}/entries/{entry_id}", dependencies=[RequireAdmin], status_code=204)
async def delete_entry(entry_id: int, write: LockedIncident) -> None:
    entry = None
    if fits_integer_id(write.session, entry_id):
        entry = await write.session.scalar(select(IncidentEntry).where(
            IncidentEntry.id == entry_id, IncidentEntry.incident_id == write.id,
        ))
    if entry is None:
        raise HTTPException(status_code=404, detail="Incident entry not found")
    if entry.deleted_at is None:
        entry.body = ""
        entry.deleted_by = write.actor
        entry.deleted_at = write.now
        await mark_incident_updated(write.session, write.id, write.now, write.actor)


async def _finish_link_additions(write: IncidentWrite, model: LinkModel, result: LinkBatch) -> LinkResponse:
    if result.added:
        await mark_incident_updated(write.session, write.id, write.now, write.actor)
        record_link_additions(write.session, write.id, write.actor, write.now, (model, result))
    return LinkResponse.model_validate(result)


@router.post("/{id}/events", dependencies=[RequireOperator])
async def add_events(body: TimedLinksRequest, write: LockedIncident) -> LinkResponse:
    result = await add_links(write.session, write.id, IncidentEvent, body.items, copy_event, write.actor, write.now)
    return await _finish_link_additions(write, IncidentEvent, result)


@router.post("/{id}/alerts", dependencies=[RequireOperator])
async def add_alerts(body: TimedLinksRequest, write: LockedIncident, settings: AppSettings) -> LinkResponse:
    result = await add_alert_links(
        write.session, write.id, body.items, settings.perf_sample_interval_seconds, write.actor, write.now,
    )
    return await _finish_link_additions(write, IncidentAlert, result)


@router.post("/{id}/snapshots", dependencies=[RequireOperator])
async def add_snapshots(body: SnapshotLinksRequest, write: LockedIncident) -> LinkResponse:
    result = await add_links(
        write.session, write.id, IncidentSnapshot, body.snapshot_ids, reference_snapshot, write.actor, write.now,
    )
    return await _finish_link_additions(write, IncidentSnapshot, result)


async def _unlink(write: IncidentWrite, model: LinkModel, link_id: int) -> None:
    removed = None
    if fits_integer_id(write.session, link_id):
        removed = await write.session.scalar(
            delete(model).where(model.id == link_id, model.incident_id == write.id).returning(model.id)
        )
    if removed is None:
        raise HTTPException(status_code=404, detail="Incident link not found")
    await mark_incident_updated(write.session, write.id, write.now, write.actor)
    write.session.add(IncidentEntry(
        incident_id=write.id, kind="link", body=f"{LINK_NAMES[model]} 1 件の紐付けを外しました。",
        author=write.actor, created_at=write.now,
    ))


@router.delete("/{id}/events/{link_id}", dependencies=[RequireOperator], status_code=204)
async def unlink_event(link_id: int, write: LockedIncident) -> None:
    await _unlink(write, IncidentEvent, link_id)


@router.delete("/{id}/alerts/{link_id}", dependencies=[RequireOperator], status_code=204)
async def unlink_alert(link_id: int, write: LockedIncident) -> None:
    await _unlink(write, IncidentAlert, link_id)


@router.delete("/{id}/snapshots/{link_id}", dependencies=[RequireOperator], status_code=204)
async def unlink_snapshot(link_id: int, write: LockedIncident) -> None:
    await _unlink(write, IncidentSnapshot, link_id)
