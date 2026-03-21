"""Retention purge and public config API."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from vcenter_event_assistant.db.models import EventRecord
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.ingestion import purge_old_events
from vcenter_event_assistant.settings import get_settings


@pytest.mark.asyncio
async def test_get_app_config(client: AsyncClient) -> None:
    r = await client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert data["event_retention_days"] == 7
    assert data["metric_retention_days"] == 7


@pytest.mark.asyncio
async def test_purge_old_events_removes_only_stale_rows(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "retention-vc",
            "host": "vc.example",
            "port": 443,
            "username": "u",
            "password": "p",
            "is_enabled": True,
        },
    )
    assert r.status_code == 201
    vid = uuid.UUID(r.json()["id"])

    os.environ["EVENT_RETENTION_DAYS"] = "7"
    get_settings.cache_clear()
    try:
        old = datetime.now(timezone.utc) - timedelta(days=10)
        recent = datetime.now(timezone.utc) - timedelta(days=1)
        async with session_scope() as session:
            session.add(
                EventRecord(
                    vcenter_id=vid,
                    occurred_at=old,
                    event_type="t",
                    message="m",
                    vmware_key=1,
                    notable_score=0,
                )
            )
            session.add(
                EventRecord(
                    vcenter_id=vid,
                    occurred_at=recent,
                    event_type="t",
                    message="m2",
                    vmware_key=2,
                    notable_score=0,
                )
            )

        async with session_scope() as session:
            n = await purge_old_events(session)
        assert n == 1

        async with session_scope() as session:
            cnt = await session.execute(select(func.count()).select_from(EventRecord))
        assert cnt.scalar() == 1
    finally:
        os.environ.pop("EVENT_RETENTION_DAYS", None)
        get_settings.cache_clear()
