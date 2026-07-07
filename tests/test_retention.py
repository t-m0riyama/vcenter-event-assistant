"""Retention purge and public config API."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from vcenter_event_assistant.db.models import (
    AlertHistory,
    AlertRule,
    DigestRecord,
    EventRecord,
    IncidentTimelineManualSnapshot,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.ingestion import (
    purge_old_alert_history,
    purge_old_digest_records,
    purge_old_events,
    purge_old_incident_timeline_snapshots,
)
from vcenter_event_assistant.settings import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_get_app_config(client: AsyncClient) -> None:
    r = await client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert data["event_retention_days"] == 7
    assert data["metric_retention_days"] == 7
    assert data["perf_sample_interval_seconds"] == 300


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
            n = await purge_old_events(session, settings=get_settings())
        assert n == 1

        async with session_scope() as session:
            cnt = await session.execute(select(func.count()).select_from(EventRecord))
        assert cnt.scalar() == 1
    finally:
        os.environ.pop("EVENT_RETENTION_DAYS", None)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_purge_old_alert_history_removes_only_stale_rows() -> None:
    os.environ["ALERT_HISTORY_RETENTION_DAYS"] = "90"
    get_settings.cache_clear()
    try:
        old = datetime.now(timezone.utc) - timedelta(days=100)
        recent = datetime.now(timezone.utc) - timedelta(days=1)
        async with session_scope() as session:
            rule = AlertRule(
                name="purge-hist", rule_type="event_score", config={"threshold": 50}
            )
            session.add(rule)
            await session.flush()
            session.add(
                AlertHistory(
                    rule_id=rule.id,
                    state="firing",
                    context_key="t",
                    notified_at=old,
                    channel="email",
                    success=True,
                )
            )
            session.add(
                AlertHistory(
                    rule_id=rule.id,
                    state="firing",
                    context_key="t2",
                    notified_at=recent,
                    channel="email",
                    success=True,
                )
            )

        async with session_scope() as session:
            n = await purge_old_alert_history(session, settings=get_settings())
        assert n == 1

        async with session_scope() as session:
            cnt = await session.execute(select(func.count()).select_from(AlertHistory))
        assert cnt.scalar() == 1
    finally:
        os.environ.pop("ALERT_HISTORY_RETENTION_DAYS", None)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_purge_old_digest_records_removes_only_stale_rows() -> None:
    os.environ["DIGEST_RETENTION_DAYS"] = "30"
    get_settings.cache_clear()
    try:
        old = datetime.now(timezone.utc) - timedelta(days=40)
        recent = datetime.now(timezone.utc) - timedelta(days=1)
        async with session_scope() as session:
            session.add(
                DigestRecord(
                    period_start=old,
                    period_end=old,
                    kind="daily",
                    body_markdown="old",
                    status="ok",
                    created_at=old,
                )
            )
            session.add(
                DigestRecord(
                    period_start=recent,
                    period_end=recent,
                    kind="daily",
                    body_markdown="new",
                    status="ok",
                    created_at=recent,
                )
            )

        async with session_scope() as session:
            n = await purge_old_digest_records(session, settings=get_settings())
        assert n == 1

        async with session_scope() as session:
            cnt = await session.execute(select(func.count()).select_from(DigestRecord))
        assert cnt.scalar() == 1
    finally:
        os.environ.pop("DIGEST_RETENTION_DAYS", None)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_purge_old_incident_timeline_snapshots_removes_only_stale_rows() -> None:
    os.environ["INCIDENT_TIMELINE_SNAPSHOT_RETENTION_DAYS"] = "7"
    get_settings.cache_clear()
    try:
        old = datetime.now(timezone.utc) - timedelta(days=10)
        recent = datetime.now(timezone.utc) - timedelta(days=1)
        async with session_scope() as session:
            session.add(
                IncidentTimelineManualSnapshot(
                    from_time=old,
                    to_time=old,
                    timestamp_utc=old,
                    operator_note="old",
                    created_at=old,
                )
            )
            session.add(
                IncidentTimelineManualSnapshot(
                    from_time=recent,
                    to_time=recent,
                    timestamp_utc=recent,
                    operator_note="new",
                    created_at=recent,
                )
            )

        async with session_scope() as session:
            n = await purge_old_incident_timeline_snapshots(
                session, settings=get_settings()
            )
        assert n == 1

        async with session_scope() as session:
            cnt = await session.execute(
                select(func.count()).select_from(IncidentTimelineManualSnapshot)
            )
        assert cnt.scalar() == 1
    finally:
        os.environ.pop("INCIDENT_TIMELINE_SNAPSHOT_RETENTION_DAYS", None)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_purge_skips_when_retention_days_zero() -> None:
    os.environ["ALERT_HISTORY_RETENTION_DAYS"] = "0"
    get_settings.cache_clear()
    try:
        old = datetime.now(timezone.utc) - timedelta(days=365)
        async with session_scope() as session:
            rule = AlertRule(
                name="purge-skip", rule_type="event_score", config={"threshold": 50}
            )
            session.add(rule)
            await session.flush()
            session.add(
                AlertHistory(
                    rule_id=rule.id,
                    state="firing",
                    context_key="t",
                    notified_at=old,
                    channel="email",
                    success=True,
                )
            )

        async with session_scope() as session:
            n = await purge_old_alert_history(session, settings=get_settings())
        assert n == 0

        async with session_scope() as session:
            cnt = await session.execute(select(func.count()).select_from(AlertHistory))
        assert cnt.scalar() == 1
    finally:
        os.environ.pop("ALERT_HISTORY_RETENTION_DAYS", None)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_get_app_config_reports_chat_web_search_availability(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = await client.get("/api/config")
    assert r.status_code == 200
    assert r.json()["chat_web_search_available"] is False

    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    get_settings.cache_clear()
    r = await client.get("/api/config")
    assert r.status_code == 200
    assert r.json()["chat_web_search_available"] is True
