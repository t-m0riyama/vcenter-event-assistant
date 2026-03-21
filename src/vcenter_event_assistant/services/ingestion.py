"""Persist collected events and metrics."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.collectors.events import fetch_events_blocking
from vcenter_event_assistant.collectors.perf import sample_hosts_blocking
from vcenter_event_assistant.db.models import EventRecord, IngestionState, MetricSample, VCenter
from vcenter_event_assistant.rules.notable import score_event
from vcenter_event_assistant.settings import get_settings


async def ingest_events_for_vcenter(session: AsyncSession, vcenter: VCenter) -> int:
    """Fetch and store new events. Returns number of rows inserted."""
    state = await session.execute(
        select(IngestionState).where(
            IngestionState.vcenter_id == vcenter.id,
            IngestionState.kind == "events",
        )
    )
    row = state.scalar_one_or_none()
    since: datetime | None = None
    if row and row.cursor_value:
        since = datetime.fromisoformat(row.cursor_value)
        # advance window slightly to reduce duplicates at boundary
        since = since - timedelta(seconds=1)

    normalized, max_ts = await asyncio.to_thread(
        fetch_events_blocking,
        host=vcenter.host,
        port=vcenter.port,
        username=vcenter.username,
        password=vcenter.password,
        since=since,
    )

    inserted = 0
    for r in normalized:
        exists = await session.execute(
            select(EventRecord.id).where(
                EventRecord.vcenter_id == vcenter.id,
                EventRecord.vmware_key == int(r["vmware_key"]),
            )
        )
        if exists.scalar_one_or_none() is not None:
            continue

        nr = score_event(
            event_type=r["event_type"],
            severity=r.get("severity"),
            message=r["message"],
        )
        ev = EventRecord(
            vcenter_id=vcenter.id,
            occurred_at=r["occurred_at"],
            event_type=r["event_type"],
            message=r["message"],
            severity=r.get("severity"),
            user_name=r.get("user_name"),
            entity_name=r.get("entity_name"),
            entity_type=r.get("entity_type"),
            vmware_key=int(r["vmware_key"]),
            chain_id=r.get("chain_id"),
            notable_score=nr.score,
            notable_tags=nr.tags,
        )
        session.add(ev)
        inserted += 1

    if row is None:
        row = IngestionState(vcenter_id=vcenter.id, kind="events", cursor_value=None)
        session.add(row)
        await session.flush()

    if max_ts is not None:
        row.cursor_value = max_ts.isoformat()
    elif since is not None:
        row.cursor_value = since.isoformat()
    else:
        row.cursor_value = datetime.now(timezone.utc).isoformat()

    return inserted


async def ingest_metrics_for_vcenter(session: AsyncSession, vcenter: VCenter) -> int:
    """Sample host metrics and store rows."""
    rows = await asyncio.to_thread(
        sample_hosts_blocking,
        host=vcenter.host,
        port=vcenter.port,
        username=vcenter.username,
        password=vcenter.password,
    )

    inserted = 0
    for r in rows:
        dup = await session.execute(
            select(MetricSample.id).where(
                MetricSample.vcenter_id == vcenter.id,
                MetricSample.sampled_at == r["sampled_at"],
                MetricSample.entity_moid == r["entity_moid"],
                MetricSample.metric_key == r["metric_key"],
            )
        )
        if dup.scalar_one_or_none() is not None:
            continue
        ms = MetricSample(
            vcenter_id=vcenter.id,
            sampled_at=r["sampled_at"],
            entity_type=r["entity_type"],
            entity_moid=r["entity_moid"],
            entity_name=r["entity_name"],
            metric_key=r["metric_key"],
            value=float(r["value"]),
        )
        session.add(ms)
        inserted += 1
    return inserted


async def purge_old_events(session: AsyncSession) -> int:
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.event_retention_days)
    res = await session.execute(delete(EventRecord).where(EventRecord.occurred_at < cutoff))
    return res.rowcount or 0


async def purge_old_metrics(session: AsyncSession) -> int:
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.metric_retention_days)
    res = await session.execute(delete(MetricSample).where(MetricSample.sampled_at < cutoff))
    return res.rowcount or 0


async def list_enabled_vcenters(session: AsyncSession) -> list[VCenter]:
    q = await session.execute(select(VCenter).where(VCenter.is_enabled.is_(True)))
    return list(q.scalars().all())
