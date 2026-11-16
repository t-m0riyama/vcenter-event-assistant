"""Retention purge and public config API."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text

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
    purge_old_incident_timeline_snapshot_results,
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
    monkeypatch.setenv("WEB_RESEARCH_ENABLED", "1")
    get_settings.cache_clear()
    r = await client.get("/api/config")
    assert r.status_code == 200
    assert r.json()["chat_web_search_available"] is True


_RESULT = {
    "from_utc": "2026-03-22T00:00:00Z",
    "to_utc": "2026-03-22T01:00:00Z",
    "bucket_seconds": 60,
    "overview": [],
    "items": [],
    "truncated": False,
    "total_items": 0,
    "highlights": {"first_signal": None, "top_entities": [], "new_event_types": []},
}
_VIEW_REQUEST = {"from": "2026-03-22T00:00:00Z", "to": "2026-03-22T01:00:00Z"}


async def _add_snapshot_with_result(note: str, age: timedelta) -> None:
    created = datetime.now(timezone.utc) - age
    async with session_scope() as session:
        session.add(
            IncidentTimelineManualSnapshot(
                from_time=created,
                to_time=created,
                timestamp_utc=created,
                operator_note=note,
                created_at=created,
                build_request_payload=_VIEW_REQUEST,
                view_request_payload=_VIEW_REQUEST,
                result_payload=_RESULT,
            )
        )


async def _snapshot_state() -> dict[str, tuple[bool, bool]]:
    """メモ -> (result_payload が SQL の NULL か, view_request_payload が残っているか)。"""
    async with session_scope() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT operator_note, result_payload IS NULL, view_request_payload IS NOT NULL "
                    "FROM incident_timeline_manual_snapshots"
                )
            )
        ).all()
    return {note: (bool(is_null), bool(has_req)) for note, is_null, has_req in rows}


@pytest.mark.asyncio
async def test_result_retention_default_keeps_results() -> None:
    assert get_settings().incident_timeline_snapshot_result_retention_days == 0
    await _add_snapshot_with_result("ancient", timedelta(days=300))
    async with session_scope() as session:
        n = await purge_old_incident_timeline_snapshot_results(session, settings=get_settings())
    assert n == 0
    assert await _snapshot_state() == {"ancient": (False, True)}


@pytest.mark.asyncio
async def test_result_retention_nulls_only_results_older_than_n_days() -> None:
    os.environ["INCIDENT_TIMELINE_SNAPSHOT_RESULT_RETENTION_DAYS"] = "7"
    get_settings.cache_clear()
    try:
        await _add_snapshot_with_result("old", timedelta(days=7, minutes=1))
        await _add_snapshot_with_result("just-inside", timedelta(days=7) - timedelta(minutes=1))
        await _add_snapshot_with_result("recent", timedelta(days=1))
        async with session_scope() as session:
            n = await purge_old_incident_timeline_snapshot_results(session, settings=get_settings())
        assert n == 1
        # 行・条件は残り、結果だけが SQL の NULL（JSON の null ではない）になる
        assert await _snapshot_state() == {
            "old": (True, True),
            "just-inside": (False, True),
            "recent": (False, True),
        }
        # すでに NULL の行は触らない（2 回目は 0 件）
        async with session_scope() as session:
            assert await purge_old_incident_timeline_snapshot_results(session, settings=get_settings()) == 0
    finally:
        os.environ.pop("INCIDENT_TIMELINE_SNAPSHOT_RESULT_RETENTION_DAYS", None)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_result_retention_longer_than_snapshot_retention_is_harmless() -> None:
    os.environ["INCIDENT_TIMELINE_SNAPSHOT_RETENTION_DAYS"] = "7"
    os.environ["INCIDENT_TIMELINE_SNAPSHOT_RESULT_RETENTION_DAYS"] = "30"
    get_settings.cache_clear()
    try:
        await _add_snapshot_with_result("old", timedelta(days=10))
        async with session_scope() as session:
            settings = get_settings()
            assert await purge_old_incident_timeline_snapshot_results(session, settings=settings) == 0
            assert await purge_old_incident_timeline_snapshots(session, settings=settings) == 1
    finally:
        os.environ.pop("INCIDENT_TIMELINE_SNAPSHOT_RETENTION_DAYS", None)
        os.environ.pop("INCIDENT_TIMELINE_SNAPSHOT_RESULT_RETENTION_DAYS", None)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_snapshot_without_result_shows_no_result_in_api(client) -> None:
    os.environ["INCIDENT_TIMELINE_SNAPSHOT_RESULT_RETENTION_DAYS"] = "7"
    get_settings.cache_clear()
    try:
        await _add_snapshot_with_result("old", timedelta(days=8))
        async with session_scope() as session:
            await purge_old_incident_timeline_snapshot_results(session, settings=get_settings())
        listed = (await client.get("/api/incident-timeline/snapshots/manual")).json()["items"]
        assert listed[0]["has_result"] is False
        assert listed[0]["view_request"] is not None
        detail = (await client.get(f"/api/incident-timeline/snapshots/manual/{listed[0]['snapshot_id']}")).json()
        assert detail["result"] is None
        assert detail["has_result"] is False
    finally:
        os.environ.pop("INCIDENT_TIMELINE_SNAPSHOT_RESULT_RETENTION_DAYS", None)
        get_settings.cache_clear()


def test_result_retention_setting_range_and_env_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INCIDENT_TIMELINE_SNAPSHOT_RESULT_RETENTION_DAYS", "14")
    get_settings.cache_clear()
    try:
        assert get_settings().incident_timeline_snapshot_result_retention_days == 14
        monkeypatch.setenv("INCIDENT_TIMELINE_SNAPSHOT_RESULT_RETENTION_DAYS", "-1")
        get_settings.cache_clear()
        with pytest.raises(Exception):  # noqa: B017 - pydantic の ValidationError
            get_settings()
    finally:
        monkeypatch.delenv("INCIDENT_TIMELINE_SNAPSHOT_RESULT_RETENTION_DAYS", raising=False)
        get_settings.cache_clear()
