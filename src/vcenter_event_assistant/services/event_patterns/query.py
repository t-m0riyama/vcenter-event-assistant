"""障害パターンごとに判定の材料を子表から読む。"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.datetime_utils import to_utc
from vcenter_event_assistant.db.models import EventEntity, EventRecord
from vcenter_event_assistant.db.sqlite_hints import indexed_by
from vcenter_event_assistant.services.event_patterns.definitions import BUILTIN_PATTERNS, EventPattern
from vcenter_event_assistant.services.event_patterns.detection import PatternDetection, PatternEvent, detect_pattern

PATTERN_ROW_LIMIT = 10_000
_EVENT_TYPE_TIME_INDEX = "ix_events_event_type_occurred_at"


def _pattern_rows_statement(
    pattern: EventPattern,
    from_utc: datetime,
    until_utc: datetime,
    vcenter_id: UUID | None,
    entity_moid: str | None,
) -> Select:
    entity_types = EventEntity.entity_type.in_(sorted(pattern.target.entity_types))
    if "object" in pattern.target.roles and "HostSystem" in pattern.target.entity_types:
        # objectType の無い EventEx も、ホストの moid を持つときは材料にする。
        entity_types = or_(
            entity_types,
            and_(
                EventEntity.role == "object",
                EventEntity.entity_type.is_(None),
                func.substr(EventEntity.entity_moid, 1, 5) == "host-",
            ),
        )

    stmt = (
        select(
            EventRecord.id,
            EventRecord.vcenter_id,
            EventRecord.occurred_at,
            EventRecord.event_type,
            EventEntity.entity_moid,
            EventEntity.entity_name,
            EventEntity.entity_type,
        )
        .select_from(EventRecord)
        .join(EventEntity, EventEntity.event_id == EventRecord.id)
        # 統計の無い SQLite でも、vCenter の期間内にある全種別のイベントを読まない。
        .with_hint(EventRecord.__table__, indexed_by(_EVENT_TYPE_TIME_INDEX), dialect_name="sqlite")
        .where(
            EventRecord.event_type.in_(sorted({name for step in pattern.steps for name in step.event_types})),
            EventRecord.occurred_at >= from_utc - timedelta(minutes=pattern.within_minutes),
            EventRecord.occurred_at < until_utc,
            EventEntity.role.in_(sorted(pattern.target.roles)),
            entity_types,
            EventEntity.entity_moid.is_not(None),
            EventEntity.entity_moid != "",
        )
    )
    if vcenter_id is not None:
        stmt = stmt.where(EventRecord.vcenter_id == vcenter_id)
    if entity_moid is not None:
        stmt = stmt.where(EventEntity.entity_moid == entity_moid)

    # 同じイベントと moid の行では名前と種別がそろう行を優先し、同順位は子表の ID 順にする。
    has_name = and_(EventEntity.entity_name.is_not(None), EventEntity.entity_name != "")
    return stmt.order_by(
        EventEntity.vcenter_id,
        EventEntity.entity_moid,
        EventRecord.occurred_at,
        EventRecord.id,
        has_name.desc(),
        EventEntity.entity_type.is_not(None).desc(),
        EventEntity.id,
    ).limit(PATTERN_ROW_LIMIT + 1)


async def query_event_patterns(
    session: AsyncSession,
    from_utc: datetime,
    until_utc: datetime,
    *,
    vcenter_id: UUID | None,
    entity_moid: str | None,
    patterns: Sequence[EventPattern] = BUILTIN_PATTERNS,
) -> tuple[list[PatternDetection], list[str]]:
    """期間内に使ったイベントがある検知と、行数の上限で省いたパターンを返す。"""
    detections: list[PatternDetection] = []
    omitted: list[str] = []
    for pattern in patterns:
        stmt = _pattern_rows_statement(pattern, from_utc, until_utc, vcenter_id, entity_moid)
        rows = (await session.execute(stmt)).all()
        if len(rows) > PATTERN_ROW_LIMIT:
            omitted.append(pattern.id)
            continue
        events = (
            PatternEvent(event_id, vc, to_utc(at), event_type, moid, name, entity_type)
            for event_id, vc, at, event_type, moid, name, entity_type in rows
        )
        # 読んだイベントはすべて until_utc より前なので、最後の時刻だけで期間内か分かる。
        detections.extend(d for d in detect_pattern(pattern, events) if d.last_utc >= from_utc)
    return detections, omitted
