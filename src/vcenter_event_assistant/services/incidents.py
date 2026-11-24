"""インシデントの読み取り、経過と紐付けを扱う。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from sqlite3 import SQLITE_CONSTRAINT_FOREIGNKEY, SQLITE_CONSTRAINT_UNIQUE
from typing import Literal, Protocol, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, joinedload

from vcenter_event_assistant.auth.timeutil import as_utc
from vcenter_event_assistant.db.models import (
    AlertHistory,
    EventRecord,
    Incident,
    IncidentAlert,
    IncidentEntry,
    IncidentEvent,
    IncidentSnapshot,
    IncidentTimelineManualSnapshot,
    VCenter,
)
from vcenter_event_assistant.services.alert_history_read import resolve_alert_history_targets
from vcenter_event_assistant.services.sql_like import contains_case_insensitive

MAX_NOTES = 1000
COPY_TEXT_LIMIT = 2000
Link = IncidentEvent | IncidentAlert | IncidentSnapshot
LinkModel = type[IncidentEvent] | type[IncidentAlert] | type[IncidentSnapshot]
IncidentStatus = Literal["open", "monitoring", "resolved"]
LinkOutcome = Literal["added", "already_linked", "not_found", "no_result", "limit_exceeded"]


class TimedSource(Protocol):
    @property
    def id(self) -> int: ...

    def matches(self, occurred_at: datetime) -> bool: ...


Source = TypeVar("Source", bound=TimedSource | UUID)


@dataclass(frozen=True)
class LinkDecision:
    id: int | UUID
    result: LinkOutcome
    link_id: int | None = None


@dataclass(frozen=True)
class LinkBatch:
    results: list[LinkDecision]
    added: int


@dataclass(frozen=True)
class IncidentListRow:
    incident: Incident
    event_count: int
    alert_count: int
    snapshot_count: int


@dataclass(frozen=True)
class IncidentPage:
    items: list[IncidentListRow]
    total: int


@dataclass(frozen=True)
class IncidentDetails:
    incident: Incident
    entries: Sequence[IncidentEntry]
    events: Sequence[tuple[IncidentEvent, bool]]
    alerts: Sequence[tuple[IncidentAlert, bool]]
    snapshots: Sequence[tuple[int, IncidentTimelineManualSnapshot, bool]]


LINK_LIMITS: dict[LinkModel, int] = {IncidentEvent: 500, IncidentAlert: 200, IncidentSnapshot: 10}
LINK_KEY_FIELDS: dict[LinkModel, tuple[str, ...]] = {
    IncidentEvent: ("vcenter_id", "collector_id", "vmware_key"),
    IncidentAlert: ("alert_history_id", "occurred_at"),
    IncidentSnapshot: ("snapshot_id",),
}
LINK_NAMES: dict[LinkModel, str] = {
    IncidentEvent: "イベント", IncidentAlert: "通知", IncidentSnapshot: "スナップショット",
}
CHANGE_LABELS = {
    "title": "件名", "status": "状態", "level": "重大度", "assignee": "担当", "summary": "要約",
    "started_at": "開始の時刻",
}
STATUS_LABELS = {"open": "対応中", "monitoring": "様子見", "resolved": "解決"}


async def list_incidents(
    session: AsyncSession, statuses: list[IncidentStatus], q: str | None, limit: int, offset: int,
) -> IncidentPage:
    filters = [Incident.status.in_(statuses)]
    if q:
        filters.append(contains_case_insensitive(Incident.title, q))
    total = await session.scalar(select(func.count()).select_from(Incident).where(*filters))
    incidents = (await session.scalars(
        select(Incident)
        .options(defer(Incident.summary))
        .where(*filters)
        .order_by(Incident.updated_at.desc(), Incident.id)
        .limit(limit)
        .offset(offset)
    )).all()
    ids = [row.id for row in incidents]
    counts: dict[LinkModel, dict[UUID, int]] = {}
    if ids:
        for model in (IncidentEvent, IncidentAlert, IncidentSnapshot):
            result = await session.execute(
                select(model.incident_id, func.count()).where(model.incident_id.in_(ids)).group_by(model.incident_id)
            )
            counts[model] = dict(result.tuples().all())

    return IncidentPage(
        items=[
            IncidentListRow(
                incident=row,
                event_count=counts[IncidentEvent].get(row.id, 0),
                alert_count=counts[IncidentAlert].get(row.id, 0),
                snapshot_count=counts[IncidentSnapshot].get(row.id, 0),
            )
            for row in incidents
        ],
        total=total or 0,
    )


async def read_incident_detail(session: AsyncSession, incident: Incident) -> IncidentDetails:
    entries = await session.scalars(
        select(IncidentEntry).where(IncidentEntry.incident_id == incident.id)
        .order_by(IncidentEntry.created_at, IncidentEntry.id)
    )
    event_exists = select(EventRecord.id).where(
        EventRecord.vcenter_id == IncidentEvent.vcenter_id,
        EventRecord.collector_id == IncidentEvent.collector_id,
        EventRecord.vmware_key == IncidentEvent.vmware_key,
    ).exists()
    events = await session.execute(
        select(IncidentEvent, event_exists).where(IncidentEvent.incident_id == incident.id)
        .order_by(IncidentEvent.occurred_at, IncidentEvent.id)
    )
    alerts = (await session.scalars(
        select(IncidentAlert).where(IncidentAlert.incident_id == incident.id)
        .order_by(IncidentAlert.occurred_at, IncidentAlert.id)
    )).all()
    existing_alerts: set[tuple[int, int, datetime]] = set()
    if alerts:
        sources = await session.execute(
            select(AlertHistory.id, AlertHistory.rule_id, AlertHistory.occurred_at)
            .where(AlertHistory.id.in_({alert.alert_history_id for alert in alerts}))
        )
        existing_alerts = {(id, rule_id, as_utc(at)) for id, rule_id, at in sources.tuples()}
    snapshot = IncidentTimelineManualSnapshot
    snapshots = await session.execute(
        select(IncidentSnapshot.id, snapshot, snapshot.result_payload.is_not(None))
        .join(snapshot, snapshot.id == IncidentSnapshot.snapshot_id)
        .options(
            defer(snapshot.result_payload, raiseload=True),
            defer(snapshot.build_request_payload),
            defer(snapshot.view_request_payload),
            defer(snapshot.trigger_evidence),
            defer(snapshot.graph_context),
        )
        .where(IncidentSnapshot.incident_id == incident.id)
        .order_by(IncidentSnapshot.id)
    )
    return IncidentDetails(
        incident=incident,
        entries=entries.all(),
        events=events.tuples().all(),
        alerts=[
            (row, (row.alert_history_id, row.rule_id, as_utc(row.occurred_at)) in existing_alerts)
            for row in alerts
        ],
        snapshots=snapshots.tuples().all(),
    )


async def lock_incident(
    session: AsyncSession, incident_id: UUID, *, revision: UUID | None = None,
) -> bool:
    """集計や変更前の読み取りより先に、値を据え置く更新文でロックする。"""
    statement = update(Incident).where(Incident.id == incident_id)
    if revision is not None:
        statement = statement.where(Incident.revision == revision)
    touched = await session.scalar(
        statement.values(revision=Incident.revision).returning(Incident.id)
    )
    return touched is not None


async def mark_incident_updated(session: AsyncSession, incident_id: UUID, now: datetime, actor: str) -> None:
    await session.execute(update(Incident).where(Incident.id == incident_id).values(updated_at=now, updated_by=actor))


def apply_incident_patch(
    session: AsyncSession, incident: Incident, fields: Mapping[str, object], now: datetime, actor: str,
) -> None:
    changes: list[str] = []
    for field, label in CHANGE_LABELS.items():
        if field not in fields:
            continue
        previous = getattr(incident, field)
        current = fields[field]
        if field == "summary" and current is None:
            current = ""
        if isinstance(previous, datetime):
            previous = as_utc(previous)
        if previous == current:
            continue
        setattr(incident, field, current)
        if field == "status":
            incident.resolved_at = now if current == "resolved" else None
        if field == "summary":
            changes.append("要約を更新しました。")
        else:
            changes.append(f"{label}を「{_change_value(field, previous)}」から「{_change_value(field, current)}」に変えました。")
    if changes:
        incident.revision = uuid4()
        incident.updated_at = now
        incident.updated_by = actor
        session.add(IncidentEntry(
            incident_id=incident.id, kind="change", body="".join(changes), author=actor, created_at=now,
        ))


def _change_value(field: str, value: object) -> str:
    if value is None:
        return "未設定"
    if field == "status":
        return STATUS_LABELS[str(value)]
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def fits_integer_id(session: AsyncSession, id: int) -> bool:
    # PostgreSQL の Integer と SQLite の ROWID の範囲外は、存在しない ID として扱う。
    bits = 32 if session.get_bind().dialect.name == "postgresql" else 64
    return -(2 ** (bits - 1)) <= id < 2 ** (bits - 1)


async def copy_event(session: AsyncSession, source: TimedSource) -> IncidentEvent | LinkOutcome:
    row = (await session.execute(
        select(EventRecord, VCenter.name).join(VCenter, VCenter.id == EventRecord.vcenter_id)
        .where(EventRecord.id == source.id)
    )).tuples().one_or_none()
    if row is None:
        return "not_found"
    event, vcenter_name = row
    occurred_at = as_utc(event.occurred_at)
    if not source.matches(occurred_at):
        return "not_found"
    return IncidentEvent(
        event_id=event.id, vcenter_id=event.vcenter_id, collector_id=event.collector_id, vmware_key=event.vmware_key,
        vcenter_name=vcenter_name, occurred_at=occurred_at, event_type=event.event_type, severity=event.severity,
        notable_score=event.notable_score, entity_type=event.entity_type, entity_name=event.entity_name,
        entity_moid=event.entity_moid, user_name=event.user_name, message=event.message[:COPY_TEXT_LIMIT],
        user_comment=event.user_comment[:COPY_TEXT_LIMIT] if event.user_comment is not None else None,
    )


async def _copy_alerts(
    session: AsyncSession, sources: Sequence[TimedSource], perf_sample_interval_seconds: int,
) -> dict[int, IncidentAlert]:
    first_by_id: dict[int, TimedSource] = {}
    for source in sources:
        if fits_integer_id(session, source.id):
            first_by_id.setdefault(source.id, source)
    if not first_by_id:
        return {}

    rows = await session.scalars(
        select(AlertHistory).options(joinedload(AlertHistory.rule)).where(AlertHistory.id.in_(first_by_id))
    )
    alerts = [row for row in rows if first_by_id[row.id].matches(as_utc(row.occurred_at))]
    if not alerts:
        return {}

    targets = await resolve_alert_history_targets(session, alerts, perf_sample_interval_seconds)
    vcenter_ids = {target.vcenter_id for target in targets.values() if target.vcenter_id is not None}
    names = {}
    if vcenter_ids:
        vcenters = await session.execute(select(VCenter.id, VCenter.name).where(VCenter.id.in_(vcenter_ids)))
        names = dict(vcenters.tuples().all())

    copies = {}
    for alert in alerts:
        target = targets[alert.id]
        copies[alert.id] = IncidentAlert(
            alert_history_id=alert.id, rule_id=alert.rule_id, rule_name=alert.rule.name if alert.rule else None,
            rule_type=alert.rule.rule_type if alert.rule else "", alert_level=alert.alert_level, state=alert.state,
            context_key=alert.context_key, occurred_at=as_utc(alert.occurred_at), vcenter_id=target.vcenter_id,
            vcenter_name=names.get(target.vcenter_id), entity_moid=target.entity_moid, entity_name=target.entity_name,
        )
    return copies


async def add_alert_links(
    session: AsyncSession, incident_id: UUID, sources: Sequence[TimedSource], perf_sample_interval_seconds: int,
    actor: str, now: datetime,
) -> LinkBatch:
    copies = await _copy_alerts(session, sources, perf_sample_interval_seconds)

    async def load(_session: AsyncSession, source: TimedSource) -> IncidentAlert | LinkOutcome:
        return copies.get(source.id, "not_found")

    return await add_links(session, incident_id, IncidentAlert, sources, load, actor, now)


async def reference_snapshot(session: AsyncSession, source: UUID) -> IncidentSnapshot | LinkOutcome:
    snapshot = IncidentTimelineManualSnapshot
    has_result = await session.scalar(
        select(snapshot.result_payload.is_not(None)).where(snapshot.id == source)
    )
    if has_result is None:
        return "not_found"
    if not has_result:
        return "no_result"
    return IncidentSnapshot(snapshot_id=source)


async def add_links(
    session: AsyncSession,
    incident_id: UUID,
    model: LinkModel,
    sources: Sequence[Source],
    load: Callable[[AsyncSession, Source], Awaitable[Link | LinkOutcome]],
    actor: str,
    now: datetime,
) -> LinkBatch:
    results: list[LinkDecision] = []
    if not sources:
        return LinkBatch(results=results, added=0)
    fields = LINK_KEY_FIELDS[model]
    columns = [getattr(model, field) for field in fields]
    rows = await session.execute(select(model.id, *columns).where(model.incident_id == incident_id))
    existing = {_link_key(values): link_id for link_id, *values in rows}
    remaining = LINK_LIMITS[model] - len(existing)
    added = 0
    seen: set[UUID | int] = set()
    for source in sources:
        source_id = source if isinstance(source, UUID) else source.id
        if source_id in seen:
            continue
        seen.add(source_id)
        if isinstance(source_id, int) and not fits_integer_id(session, source_id):
            results.append(LinkDecision(id=source_id, result="not_found"))
            continue
        link = await load(session, source)
        if isinstance(link, str):
            results.append(LinkDecision(id=source_id, result=link))
            continue

        key = _link_key(getattr(link, field) for field in fields)
        if key in existing:
            results.append(LinkDecision(id=source_id, result="already_linked", link_id=existing[key]))
            continue
        if added >= remaining:
            results.append(LinkDecision(id=source_id, result="limit_exceeded"))
            continue

        link.incident_id = incident_id
        link.added_by = actor
        link.added_at = now
        try:
            async with session.begin_nested():
                session.add(link)
                await session.flush()
        except IntegrityError as exc:
            if _is_constraint(exc, "23505", SQLITE_CONSTRAINT_UNIQUE):
                existing_id = await session.scalar(select(model.id).where(
                    model.incident_id == incident_id, *(column == value for column, value in zip(columns, key, strict=True)),
                ))
                if existing_id is not None:
                    results.append(LinkDecision(id=source_id, result="already_linked", link_id=existing_id))
                    continue
            if model is IncidentSnapshot and _is_constraint(exc, "23503", SQLITE_CONSTRAINT_FOREIGNKEY):
                results.append(LinkDecision(id=source_id, result="not_found"))
                continue
            raise
        results.append(LinkDecision(id=source_id, result="added", link_id=link.id))
        existing[key] = link.id
        added += 1
    return LinkBatch(results=results, added=added)


def _is_constraint(exc: IntegrityError, sqlstate: str, sqlite_code: int) -> bool:
    return (
        getattr(exc.orig, "sqlstate", None) == sqlstate
        or getattr(exc.orig, "sqlite_errorcode", None) == sqlite_code
    )


def _link_key(values: Iterable[object]) -> tuple[object, ...]:
    return tuple(as_utc(value) if isinstance(value, datetime) else value for value in values)


def record_link_additions(
    session: AsyncSession, incident_id: UUID, actor: str, now: datetime, *batches: tuple[LinkModel, LinkBatch],
) -> None:
    if not any(batch.added for _, batch in batches):
        return
    descriptions: list[str] = []
    for model, batch in batches:
        if batch.results:
            descriptions.append(f"{LINK_NAMES[model]} {batch.added} 件を追加しました。")
            counts = Counter(item.result for item in batch.results)
            for result, message in (
                ("already_linked", "紐付け済みでした"),
                ("not_found", "見つかりませんでした"),
                ("no_result", "結果がありませんでした"),
                ("limit_exceeded", "上限を超えました"),
            ):
                if count := counts[result]:
                    descriptions.append(f"{count} 件は{message}。")
    session.add(IncidentEntry(
        incident_id=incident_id, kind="link", body="".join(descriptions), author=actor, created_at=now,
    ))
