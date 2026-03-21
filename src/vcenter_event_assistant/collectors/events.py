"""vCenter event collection (blocking pyVmomi; run in a thread)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pyVmomi import vim

from vcenter_event_assistant.collectors.connection import connect_vcenter, disconnect


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def fetch_events_blocking(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    since: datetime | None,
    max_pages: int = 100,
) -> tuple[list[dict[str, Any]], datetime | None]:
    """
    Pull events from vCenter since ``since`` (inclusive window start).
    Returns normalized dicts and the max ``occurred_at`` in the batch.
    """
    si = connect_vcenter(host=host, port=port, username=username, password=password)
    try:
        content = si.RetrieveContent()
        em = content.eventManager
        filt = vim.event.EventFilterSpec()
        filt.time = vim.event.EventFilterSpec.ByTime()
        end = datetime.now(timezone.utc)
        filt.time.endTime = end
        if since:
            filt.time.beginTime = _ensure_aware(since)
        else:
            filt.time.beginTime = end - timedelta(days=1)

        collector = em.CreateCollectorForEvents(filt)
        raw: list[Any] = []
        try:
            for _ in range(max_pages):
                page = collector.ReadNextEvents(500)
                if not page:
                    break
                raw.extend(page)
        finally:
            collector.DestroyCollector()

        normalized: list[dict[str, Any]] = []
        max_ts: datetime | None = None
        for e in raw:
            row = normalize_event(e)
            normalized.append(row)
            ot = row["occurred_at"]
            if max_ts is None or ot > max_ts:
                max_ts = ot
        return normalized, max_ts
    finally:
        disconnect(si)


def normalize_event(e: Any) -> dict[str, Any]:
    """Map a pyVmomi event object to a plain dict for persistence."""
    event_type = type(e).__name__
    created = getattr(e, "createdTime", None) or datetime.now(timezone.utc)
    created = _ensure_aware(created)
    message = getattr(e, "fullFormattedMessage", None) or str(e)
    vmware_key = int(getattr(e, "key", 0) or 0)
    chain_id = getattr(e, "chainId", None)
    if chain_id is not None:
        chain_id = int(chain_id)

    severity = getattr(e, "severity", None)
    if severity is not None:
        severity = str(severity).lower()

    entity_name = None
    entity_type = None
    ent = getattr(e, "entity", None)
    if ent is not None:
        entity_name = getattr(ent, "name", None)
        entity_type = type(ent).__name__

    user_name = getattr(e, "userName", None)

    return {
        "occurred_at": created,
        "event_type": event_type,
        "message": message,
        "severity": severity,
        "user_name": user_name,
        "entity_name": entity_name,
        "entity_type": entity_type,
        "vmware_key": vmware_key,
        "chain_id": chain_id,
    }
