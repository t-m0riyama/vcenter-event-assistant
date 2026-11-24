"""Persist collected events and metrics."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, null, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from vcenter_event_assistant_plugin_api import EventEntityInput, EventInput, limits
from vcenter_event_assistant_plugin_api.vmware import entity_priority

from vcenter_event_assistant.collectors.events import fetch_events_blocking
from vcenter_event_assistant.collectors.perf import sample_hosts_blocking
from vcenter_event_assistant.db.models import (
    AlertHistory,
    DigestRecord,
    EventEntity,
    EventRecord,
    IncidentTimelineManualSnapshot,
    IngestionState,
    MetricSample,
    VCenter,
)
from vcenter_event_assistant.mocks.mock_collectors import (
    fetch_mock_events_blocking,
    sample_mock_hosts_blocking,
)
from vcenter_event_assistant.plugins.builtin import EventsCollector, _event
from vcenter_event_assistant.rules.notable import clamp_notable_total, score_event
from vcenter_event_assistant.services.event_scores import load_event_score_delta_map
from vcenter_event_assistant.settings import Settings


logger = logging.getLogger(__name__)


async def _insert_on_conflict_do_nothing(
    session: AsyncSession,
    model: type[Any],
    values: dict[str, Any],
    *,
    index_elements: list[str],
    returning: tuple[Any, ...] = (),
):
    """PostgreSQL / SQLite 向け INSERT ... ON CONFLICT DO NOTHING を実行する。"""
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        from sqlalchemy.dialects.sqlite import insert as dialect_insert

    stmt = dialect_insert(model).values(**values).on_conflict_do_nothing(
        index_elements=index_elements
    )
    if returning:
        stmt = stmt.returning(*returning)
    return await session.execute(stmt)


def _within_limit(value: str | None, limit: int) -> str | None:
    return value if isinstance(value, str) and len(value) <= limit else None


def _event_entities_for_storage(
    event: EventInput, entity_moid: str | None,
) -> tuple[EventEntityInput, ...]:
    """子の型・列長・重複を整え、残った対象で主な対象の指定を補正する。"""
    entities: dict[tuple[str, int], EventEntityInput] = {}
    for entity in event.entities:
        role = entity.role
        if not isinstance(role, str) or not 1 <= len(role) <= limits.MAX_EVENT_ENTITY_ROLE:
            logger.warning("discarded event entity with invalid role: vmware_key=%s", event.vmware_key)
            continue
        position = entity.position
        if not isinstance(position, int) or isinstance(position, bool) or not 0 <= position <= 2**31 - 1:
            logger.warning("discarded event entity with invalid position: vmware_key=%s", event.vmware_key)
            continue
        key = (role, position)
        if key in entities:
            continue
        entities[key] = replace(
            entity,
            entity_moid=_within_limit(entity.entity_moid, limits.MAX_ENTITY_MOID),
            entity_type=_within_limit(entity.entity_type, limits.MAX_EVENT_ENTITY_TYPE),
            entity_name=limits.truncate(entity.entity_name, limits.MAX_ENTITY_NAME)
            if isinstance(entity.entity_name, str) else None,
            is_primary=bool(entity.is_primary),
        )

    if not entities or sum(entity.is_primary for entity in entities.values()) == 1:
        return tuple(entities.values())

    if entity_moid:
        candidates: Iterable[EventEntityInput] = (entity for entity in entities.values() if entity.entity_moid == entity_moid)
    elif event.entity_name is not None:
        candidates = (entity for entity in entities.values() if entity.entity_name == event.entity_name)
    else:
        candidates = iter(())
    primary = min(candidates, key=entity_priority, default=None)
    return tuple(replace(entity, is_primary=entity is primary) for entity in entities.values())


async def persist_events(
    session: AsyncSession,
    vcenter_id: UUID,
    collector_id: str,
    events: Iterable[EventInput],
) -> int:
    """イベントを 1 行ずつ入れ、新規イベントの対象だけをまとめて保存する。"""
    deltas = await load_event_score_delta_map(session)
    insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    insert_event = insert(EventRecord).on_conflict_do_nothing(
        index_elements=["vcenter_id", "collector_id", "vmware_key"],
    ).returning(EventRecord.id)

    inserted = 0
    entity_rows: list[dict[str, Any]] = []
    for event in events:
        notable = score_event(
            event_type=event.event_type,
            severity=event.severity,
            message=event.message,
        )
        entity_moid = _within_limit(event.entity_moid, limits.MAX_ENTITY_MOID)
        event_id = await session.scalar(insert_event.values(
            collector_id=collector_id,
            vcenter_id=vcenter_id,
            occurred_at=event.occurred_at,
            event_type=event.event_type,
            message=event.message,
            severity=event.severity,
            user_name=event.user_name,
            entity_name=event.entity_name,
            entity_type=event.entity_type,
            entity_moid=entity_moid,
            vmware_key=event.vmware_key,
            chain_id=event.chain_id,
            notable_score=clamp_notable_total(notable.score, deltas.get(event.event_type, 0)),
            notable_tags=notable.tags,
        ))
        if event_id is None:
            continue
        inserted += 1
        entity_rows.extend({
            "event_id": event_id,
            "vcenter_id": vcenter_id,
            "role": entity.role,
            "position": entity.position,
            "is_primary": entity.is_primary,
            "entity_type": entity.entity_type,
            "entity_moid": entity.entity_moid,
            "entity_name": entity.entity_name,
        } for entity in _event_entities_for_storage(event, entity_moid))

    if entity_rows:
        # 1 行分の文を executemany で実行し、SQLite のバインド変数上限を避ける。
        stmt = insert(EventEntity.__table__).on_conflict_do_nothing()
        await session.execute(stmt, entity_rows)
    return inserted


async def ingest_events_for_vcenter(
    session: AsyncSession, vcenter: VCenter, *, settings: Settings
) -> int:
    """Fetch and store new events. Returns number of rows inserted."""
    state = await session.execute(
        select(IngestionState).where(
            IngestionState.vcenter_id == vcenter.id,
            IngestionState.kind == "events",
        )
    )
    row = state.scalar_one_or_none()
    since: datetime | None = None
    fetch_since: datetime | None = None
    if row and row.cursor_value:
        since = datetime.fromisoformat(row.cursor_value)
        # advance window slightly to reduce duplicates at boundary
        fetch_since = since - timedelta(seconds=1)

    if settings.mock_mode:
        normalized, max_ts = await asyncio.to_thread(
            fetch_mock_events_blocking,
            since=fetch_since,
        )
    else:
        normalized, max_ts = await asyncio.to_thread(
            fetch_events_blocking,
            host=vcenter.host,
            protocol=vcenter.protocol,
            port=vcenter.port,
            username=vcenter.username,
            password=vcenter.password,
            since=fetch_since,
            proxy_url=settings.vcenter_http_proxy,
            verify_ssl=vcenter.verify_ssl,
            ca_bundle_path=settings.vcenter_ca_bundle,
        )

    inserted = await persist_events(
        session, vcenter.id, EventsCollector.manifest.id, (_event(row) for row in normalized),
    ) if normalized else 0

    if row is None:
        row = IngestionState(vcenter_id=vcenter.id, kind="events", cursor_value=None)
        session.add(row)
        await session.flush()

    if max_ts is not None:
        row.cursor_value = max_ts.isoformat()
    elif since is None:
        row.cursor_value = datetime.now(timezone.utc).isoformat()

    return inserted


async def ingest_metrics_for_vcenter(
    session: AsyncSession, vcenter: VCenter, *, settings: Settings
) -> int:
    """Sample host metrics and store rows."""
    if settings.mock_mode:
        rows = await asyncio.to_thread(sample_mock_hosts_blocking)
    else:
        rows = await asyncio.to_thread(
            sample_hosts_blocking,
            host=vcenter.host,
            protocol=vcenter.protocol,
            port=vcenter.port,
            username=vcenter.username,
            password=vcenter.password,
            proxy_url=settings.vcenter_http_proxy,
            verify_ssl=vcenter.verify_ssl,
            ca_bundle_path=settings.vcenter_ca_bundle,
        )

    inserted = 0
    for r in rows:
        result = await _insert_on_conflict_do_nothing(
            session,
            MetricSample,
            {
                "vcenter_id": vcenter.id,
                "sampled_at": r["sampled_at"],
                "entity_type": r["entity_type"],
                "entity_moid": r["entity_moid"],
                "entity_name": r["entity_name"],
                "metric_key": r["metric_key"],
                "value": float(r["value"]),
            },
            index_elements=["vcenter_id", "sampled_at", "entity_moid", "metric_key"],
        )
        inserted += result.rowcount or 0
    return inserted


async def purge_old_events(session: AsyncSession, *, settings: Settings) -> int:
    """保持期間を超えたイベント行を削除する。

    Args:
        session: 非同期 DB セッション。

    Returns:
        削除した行数。
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.event_retention_days)
    res = await session.execute(delete(EventRecord).where(EventRecord.occurred_at < cutoff))
    return res.rowcount or 0


async def purge_old_metrics(session: AsyncSession, *, settings: Settings) -> int:
    """保持期間を超えたメトリクスサンプル行を削除する。

    Args:
        session: 非同期 DB セッション。

    Returns:
        削除した行数。
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.metric_retention_days)
    res = await session.execute(delete(MetricSample).where(MetricSample.sampled_at < cutoff))
    return res.rowcount or 0


async def purge_old_alert_history(session: AsyncSession, *, settings: Settings) -> int:
    """保持期間を超えた通知履歴行を削除する。"""
    days = settings.alert_history_retention_days
    if days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    res = await session.execute(delete(AlertHistory).where(
        AlertHistory.notified_at < cutoff,
        AlertHistory.delivery_status.notin_(["pending", "retrying"]),
    ))
    return res.rowcount or 0


async def purge_old_digest_records(session: AsyncSession, *, settings: Settings) -> int:
    """保持期間を超えたダイジェスト行を削除する。"""
    days = settings.digest_retention_days
    if days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    res = await session.execute(delete(DigestRecord).where(DigestRecord.created_at < cutoff))
    return res.rowcount or 0


async def purge_old_incident_timeline_snapshots(session: AsyncSession, *, settings: Settings) -> int:
    """保持期間を超えたインシデントタイムラインスナップショット行を削除する。"""
    days = settings.incident_timeline_snapshot_retention_days
    if days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    res = await session.execute(
        delete(IncidentTimelineManualSnapshot).where(
            IncidentTimelineManualSnapshot.created_at < cutoff,
        )
    )
    return res.rowcount or 0


async def purge_old_incident_timeline_snapshot_results(session: AsyncSession, *, settings: Settings) -> int:
    """保持期間を超えたスナップショットの保存結果（``result_payload``）だけを SQL の NULL にする。

    行・``view_request_payload``・運用メモは残す。消したあとは ``has_result`` が false になり、
    画面は保存した条件で再集計する。1 回の UPDATE で済ませ、結果の本体は読まない。
    ``None`` を値にすると JSON の null が入るので、``null()`` で SQL の NULL にする。
    """
    days = settings.incident_timeline_snapshot_result_retention_days
    if days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    res = await session.execute(
        update(IncidentTimelineManualSnapshot)
        .where(
            IncidentTimelineManualSnapshot.created_at < cutoff,
            IncidentTimelineManualSnapshot.result_payload.is_not(None),
        )
        .values(result_payload=null())
        .execution_options(synchronize_session=False)
    )
    return res.rowcount or 0


async def list_enabled_vcenters(session: AsyncSession) -> list[VCenter]:
    """``is_enabled=True`` の vCenter 行をすべて返す。

    Args:
        session: 非同期 DB セッション。

    Returns:
        有効な vCenter モデルのリスト。
    """
    q = await session.execute(select(VCenter).where(VCenter.is_enabled.is_(True)))
    return list(q.scalars().all())


async def purge_old_logs(session: AsyncSession, *, settings: Settings) -> int:
    from vcenter_event_assistant.db.models import LogRecord
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.log_retention_days)
    result = await session.execute(delete(LogRecord).where(LogRecord.effective_at < cutoff))
    return result.rowcount or 0
