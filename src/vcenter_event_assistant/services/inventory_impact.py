"""保存した観測から指定時刻の影響範囲を引く。"""

from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import Select, case, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.schemas.inventory import (
    ImpactRelation,
    ImpactStatus,
    InventoryChange,
    InventoryChanges,
    InventoryImpactGroup,
    InventoryImpactItem,
    InventoryImpactResponse,
    InventoryTarget,
)
from vcenter_event_assistant.auth.timeutil import as_utc, utcnow
from vcenter_event_assistant.db.models import (
    EventEntity,
    EventRecord,
    InventoryObject,
    InventoryRelation,
    InventorySyncRun,
    InventorySyncState,
    VCenter,
)
from vcenter_event_assistant.settings import Settings

_LIMIT = 200

# 起点から見た相手の名前と、相手が子か親かをたどる順序。
type RelationStep = tuple[str, Literal["parent", "child"]]
type GroupPath = tuple[ImpactRelation, tuple[RelationStep, ...]]

_DATASTORE_GROUPS: tuple[GroupPath, ...] = (
    ("hosts", (("host_datastore", "child"),)),
    ("vms", (("vm_datastore", "child"),)),
)
_NETWORK_GROUPS: tuple[GroupPath, ...] = (
    ("hosts", (("host_network", "child"),)),
    ("vms", (("vm_network", "child"),)),
)
_GROUP_PATHS: dict[str, tuple[GroupPath, ...]] = {
    "HostSystem": (
        ("cluster", (("host_cluster", "parent"),)),
        ("vms", (("vm_host", "child"),)),
        ("datastores", (("host_datastore", "parent"),)),
        ("networks", (("host_network", "parent"),)),
    ),
    "VirtualMachine": (
        ("hosts", (("vm_host", "parent"),)),
        ("cluster", (("vm_host", "parent"), ("host_cluster", "parent"))),
        ("datastores", (("vm_datastore", "parent"),)),
        ("networks", (("vm_network", "parent"),)),
    ),
    "ClusterComputeResource": (
        ("hosts", (("host_cluster", "child"),)),
        ("vms", (("host_cluster", "child"), ("vm_host", "child"))),
    ),
    "Datastore": _DATASTORE_GROUPS,
    "Network": _NETWORK_GROUPS,
    "DistributedVirtualPortgroup": _NETWORK_GROUPS,
    "OpaqueNetwork": _NETWORK_GROUPS,
}


def _as_of_status(
    *,
    entity_type: str | None,
    recorded_since: datetime | None,
    target: InventoryObject | None,
    at: datetime,
    prev: datetime | None,
    stale_after: timedelta,
) -> ImpactStatus:
    if entity_type is not None and entity_type not in _GROUP_PATHS:
        return "unsupported_type"
    if recorded_since is None or at < recorded_since:
        return "not_recorded"
    if target is None:
        return "unknown_target"
    if as_utc(target.first_seen_at) > at or (
        target.removed_at is not None and as_utc(target.removed_at) <= at
    ):
        return "absent_at_time"
    if prev is None or at - prev > stale_after:
        return "stale"
    return "ok"


async def _latest_event_type(
    session: AsyncSession, vcenter_id: UUID, moid: str
) -> str | None:
    return await session.scalar(
        select(EventEntity.entity_type)
        .join(EventRecord, EventRecord.id == EventEntity.event_id)
        .where(
            EventEntity.vcenter_id == vcenter_id,
            EventEntity.entity_moid == moid,
            EventEntity.entity_type.is_not(None),
        )
        .order_by(EventRecord.occurred_at.desc(), EventEntity.id.desc())
        .limit(1)
    )


async def _surrounding_observations(
    session: AsyncSession, vcenter_id: UUID, at: datetime
) -> tuple[datetime | None, datetime | None]:
    observed_at = InventorySyncRun.observed_at
    in_center = InventorySyncRun.vcenter_id == vcenter_id
    before, after = (
        await session.execute(
            select(
                select(func.max(observed_at))
                .where(in_center, observed_at <= at)
                .scalar_subquery(),
                select(func.min(observed_at))
                .where(in_center, observed_at > at)
                .scalar_subquery(),
            )
        )
    ).one()
    return (
        as_utc(before) if before is not None else None,
        as_utc(after) if after is not None else None,
    )


def _related_moids(
    vcenter_id: UUID,
    at: datetime,
    origin: str | Select[tuple[str]],
    step: RelationStep,
) -> Select[tuple[str]]:
    kind, toward = step
    source, destination = InventoryRelation.child_moid, InventoryRelation.parent_moid
    if toward == "child":
        source, destination = destination, source
    return select(destination).where(
        InventoryRelation.vcenter_id == vcenter_id,
        InventoryRelation.kind == kind,
        source == origin if isinstance(origin, str) else source.in_(origin),
        InventoryRelation.valid_from <= at,
        or_(InventoryRelation.valid_to.is_(None), InventoryRelation.valid_to > at),
    )


async def _read_group(
    session: AsyncSession, vcenter_id: UUID, moid: str, at: datetime, path: GroupPath
) -> InventoryImpactGroup:
    relation, steps = path
    related = _related_moids(vcenter_id, at, moid, steps[0])
    for step in steps[1:]:
        related = _related_moids(vcenter_id, at, related, step)
    # 同じ相手への経路が複数あっても、一覧と総数には一度だけ含める。
    endpoints = related.distinct().subquery()
    endpoint_moid = endpoints.c[0]
    name = func.coalesce(func.nullif(InventoryObject.name, ""), endpoint_moid)
    # DB の既定の照合順序によらず、同じ名前順で上限を適用する。
    collation = "C" if session.get_bind().dialect.name == "postgresql" else "BINARY"
    sort_name = name.collate(collation)
    rows = (
        await session.execute(
            select(
                endpoint_moid,
                InventoryObject.entity_type,
                name,
                InventoryObject.removed_at,
                func.count().over(),
            )
            .select_from(endpoints)
            .outerjoin(
                InventoryObject,
                (InventoryObject.vcenter_id == vcenter_id)
                & (InventoryObject.moid == endpoint_moid),
            )
            .order_by(
                func.lower(sort_name), sort_name, endpoint_moid.collate(collation)
            )
            .limit(_LIMIT)
        )
    ).all()
    return InventoryImpactGroup(
        relation=relation,
        total=rows[0][4] if rows else 0,
        items=[
            InventoryImpactItem(
                moid=other_moid,
                entity_type=entity_type,
                name=other_name,
                removed=removed_at is not None,
            )
            for other_moid, entity_type, other_name, removed_at, _ in rows
        ],
    )


async def _read_changes(
    session: AsyncSession,
    vcenter_id: UUID,
    moid: str,
    from_time: datetime,
    to_time: datetime,
) -> InventoryChanges:
    other = case(
        (InventoryRelation.child_moid == moid, InventoryRelation.parent_moid),
        else_=InventoryRelation.child_moid,
    ).label("other_moid")
    incident = select(InventoryRelation.id, InventoryRelation.kind, other).where(
        InventoryRelation.vcenter_id == vcenter_id,
        or_(
            InventoryRelation.child_moid == moid, InventoryRelation.parent_moid == moid
        ),
    )
    opening = InventoryRelation.valid_from
    closing = InventoryRelation.valid_to
    changes = union_all(
        incident.add_columns(opening.label("at"), literal(True).label("opened")).where(
            opening > from_time, opening <= to_time
        ),
        incident.add_columns(closing.label("at"), literal(False).label("opened")).where(
            closing > from_time, closing <= to_time
        ),
    ).subquery()
    name = func.coalesce(func.nullif(InventoryObject.name, ""), changes.c.other_moid)
    rows = (
        await session.execute(
            select(
                changes.c.kind,
                changes.c.other_moid,
                InventoryObject.entity_type,
                name,
                changes.c.at,
                changes.c.opened,
                func.count().over(),
            )
            .select_from(changes)
            .outerjoin(
                InventoryObject,
                (InventoryObject.vcenter_id == vcenter_id)
                & (InventoryObject.moid == changes.c.other_moid),
            )
            .order_by(changes.c.at, changes.c.id, changes.c.opened.desc())
            .limit(_LIMIT)
        )
    ).all()
    return InventoryChanges(
        total=rows[0][6] if rows else 0,
        items=[
            InventoryChange(
                kind=kind,
                other=InventoryTarget(
                    moid=other_moid, entity_type=entity_type, name=other_name
                ),
                at=as_utc(at),
                action="opened" if opened else "closed",
            )
            for kind, other_moid, entity_type, other_name, at, opened, _ in rows
        ],
    )


async def get_inventory_impact(
    session: AsyncSession,
    settings: Settings,
    *,
    vcenter_id: UUID,
    moid: str,
    at: datetime | None,
    from_time: datetime | None,
    to_time: datetime | None,
) -> InventoryImpactResponse | None:
    """None は登録されていない vCenter を表す。"""
    center = (
        await session.execute(
            select(
                VCenter.id,
                InventorySyncState.first_success_at,
                InventorySyncState.last_success_at,
            )
            .outerjoin(InventorySyncState, InventorySyncState.vcenter_id == VCenter.id)
            .where(VCenter.id == vcenter_id)
        )
    ).one_or_none()
    if center is None:
        return None

    _, first_success, last_success = center
    now = utcnow()
    last_success_at = as_utc(last_success) if last_success is not None else None
    ceiling = max(now, last_success_at or now)
    at = min(at, ceiling) if at is not None else ceiling
    recorded_since = (
        max(as_utc(first_success), now - timedelta(days=settings.event_retention_days))
        if first_success is not None
        else None
    )
    obj = await session.scalar(
        select(InventoryObject).where(
            InventoryObject.vcenter_id == vcenter_id, InventoryObject.moid == moid
        )
    )
    entity_type = (
        obj.entity_type
        if obj is not None
        else await _latest_event_type(session, vcenter_id, moid)
    )
    prev, next_observation = await _surrounding_observations(session, vcenter_id, at)
    status = _as_of_status(
        entity_type=entity_type,
        recorded_since=recorded_since,
        target=obj,
        at=at,
        prev=prev,
        stale_after=timedelta(seconds=2 * settings.inventory_sync_interval_seconds),
    )
    groups = []
    if status in {"ok", "stale", "absent_at_time"} and entity_type is not None:
        groups = [
            await _read_group(session, vcenter_id, moid, at, path)
            for path in _GROUP_PATHS[entity_type]
        ]

    result = InventoryImpactResponse(
        target=InventoryTarget(
            moid=moid, entity_type=entity_type, name=(obj.name or moid) if obj else moid
        ),
        at=at,
        status=status,
        recorded_since=recorded_since,
        last_success_at=last_success_at,
        observed_before=prev,
        observed_after=next_observation,
        groups=groups,
    )
    if from_time is not None and to_time is not None:
        changes = InventoryChanges(items=[], total=0)
        if recorded_since is not None:
            start = max(from_time, recorded_since)
            if start < to_time:
                changes = await _read_changes(session, vcenter_id, moid, start, to_time)
        result.changes = changes
    return result
