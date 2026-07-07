"""Persist collected events and metrics."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.collectors.events import fetch_events_blocking
from vcenter_event_assistant.collectors.perf import sample_hosts_blocking
from vcenter_event_assistant.db.models import (
    AlertHistory,
    DigestRecord,
    EventRecord,
    IncidentTimelineManualSnapshot,
    IngestionState,
    MetricSample,
    VCenter,
)
from vcenter_event_assistant.rules.notable import clamp_notable_total, score_event
from vcenter_event_assistant.services.event_scores import load_event_score_delta_map
from vcenter_event_assistant.settings import Settings


async def _insert_on_conflict_do_nothing(
    session: AsyncSession,
    model: type[Any],
    values: dict[str, Any],
    *,
    index_elements: list[str],
):
    """PostgreSQL / SQLite 向け INSERT ... ON CONFLICT DO NOTHING を実行する。"""
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        from sqlalchemy.dialects.sqlite import insert as dialect_insert

    stmt = dialect_insert(model).values(**values).on_conflict_do_nothing(
        index_elements=index_elements
    )
    return await session.execute(stmt)


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

    deltas = await load_event_score_delta_map(session)
    inserted = 0
    for r in normalized:
        nr = score_event(
            event_type=r["event_type"],
            severity=r.get("severity"),
            message=r["message"],
        )
        delta = deltas.get(r["event_type"], 0)
        final_score = clamp_notable_total(nr.score, delta)
        result = await _insert_on_conflict_do_nothing(
            session,
            EventRecord,
            {
                "vcenter_id": vcenter.id,
                "occurred_at": r["occurred_at"],
                "event_type": r["event_type"],
                "message": r["message"],
                "severity": r.get("severity"),
                "user_name": r.get("user_name"),
                "entity_name": r.get("entity_name"),
                "entity_type": r.get("entity_type"),
                "vmware_key": int(r["vmware_key"]),
                "chain_id": r.get("chain_id"),
                "notable_score": final_score,
                "notable_tags": nr.tags,
            },
            index_elements=["vcenter_id", "vmware_key"],
        )
        inserted += result.rowcount or 0

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
    res = await session.execute(delete(AlertHistory).where(AlertHistory.notified_at < cutoff))
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


async def list_enabled_vcenters(session: AsyncSession) -> list[VCenter]:
    """``is_enabled=True`` の vCenter 行をすべて返す。

    Args:
        session: 非同期 DB セッション。

    Returns:
        有効な vCenter モデルのリスト。
    """
    q = await session.execute(select(VCenter).where(VCenter.is_enabled.is_(True)))
    return list(q.scalars().all())
