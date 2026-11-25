"""保持期間、CASCADE と PostgreSQL の紐付けロックを検証する。"""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import delete, event, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db import session as db
from vcenter_event_assistant.db.models import Incident, IncidentEntry, IncidentSnapshot, IncidentTimelineManualSnapshot
from vcenter_event_assistant.jobs.scheduler import PURGE_RETENTION_LOCK_KEY, purge_retention
from vcenter_event_assistant.services.incidents import LinkBatch, add_links, lock_incident, reference_snapshot
from vcenter_event_assistant.services.ingestion import (
    lock_incident_snapshot_links_for_purge,
    purge_old_incident_timeline_snapshot_results,
)
from vcenter_event_assistant.settings import Settings

pytestmark = pytest.mark.asyncio
ROOT = "/api/incidents"


async def seed_snapshots():
    old = datetime.now(timezone.utc) - timedelta(days=100)
    async with db.session_scope() as session:
        rows = [
            IncidentTimelineManualSnapshot(from_time=old, to_time=old, timestamp_utc=old, created_at=old,
                                           operator_note="", result_payload={})
            for _ in range(3)
        ]
        session.add_all(rows)
        await session.flush()
        return [row.id for row in rows]


@pytest.mark.parametrize("incident_db", ["sqlite", "postgres"], indirect=True)
async def test_incident_retention_and_snapshot_protection(incident_db, open_client):
    protected, orphan, advancing = await seed_snapshots()
    expiry = datetime.now(timezone.utc) - timedelta(days=91)
    async with open_client() as client:
        paths = {}
        for title, status, snapshots in (
            ("open", "open", [advancing]), ("returned", "resolved", []),
            ("expired", "resolved", [protected]), ("remaining", "resolved", []),
        ):
            response = await client.post(ROOT, json={
                "title": title, "status": status, "snapshot_ids": [str(s) for s in snapshots],
            })
            assert response.status_code == 201
            incident = response.json()["incident"]
            paths[title] = f"{ROOT}/{incident['id']}"
            if title in {"returned", "expired"}:
                async with db.session_scope() as session:
                    await session.execute(update(Incident).where(Incident.id == UUID(incident["id"])).values(
                        resolved_at=expiry,
                    ))
            if title == "returned":
                assert (await client.patch(paths[title], json={
                    "revision": incident["revision"], "status": "open",
                })).status_code == 200
            elif title == "expired":
                assert (await client.post(f"{paths[title]}/entries", json={"body": "期限は延びない"})).status_code == 201

        disabled = Settings(incident_retention_days=0, incident_timeline_snapshot_result_retention_days=1)
        async with db.session_scope() as session:
            assert await purge_old_incident_timeline_snapshot_results(session, settings=disabled) == 1
        async with db.session_scope() as session:
            assert set(await session.scalars(select(IncidentTimelineManualSnapshot.id).where(
                IncidentTimelineManualSnapshot.result_payload.is_not(None),
            ))) == {protected, advancing}

        await purge_retention(disabled)
        assert (await client.get(paths["expired"])).status_code == 200
        async with db.session_scope() as session:
            assert await session.get(IncidentTimelineManualSnapshot, orphan) is None
            assert await session.get(IncidentTimelineManualSnapshot, protected) is not None

        await purge_retention(disabled.model_copy(update={"incident_retention_days": 90}))
        assert (await client.get(paths["expired"])).status_code == 404
        for label in ("open", "returned", "remaining"):
            assert (await client.get(paths[label])).status_code == 200
        async with db.session_scope() as session:
            assert set(await session.scalars(select(IncidentTimelineManualSnapshot.id))) == {advancing}
            assert await session.scalar(select(func.count()).select_from(IncidentSnapshot)) == 1
            assert await session.scalar(select(func.count()).select_from(IncidentEntry)) == 2


async def _create_incident(session: AsyncSession) -> UUID:
    now = datetime.now(timezone.utc)
    incident = Incident(
        title="保持期間の競合", status="open", summary="", created_by="tester", updated_by="tester",
        created_at=now, updated_at=now,
    )
    session.add(incident)
    await session.flush()
    return incident.id


async def _link_snapshot(session: AsyncSession, incident_id: UUID, snapshot_id: UUID) -> LinkBatch:
    assert await lock_incident(session, incident_id)
    return await add_links(
        session, incident_id, IncidentSnapshot, [snapshot_id], reference_snapshot,
        "tester", datetime.now(timezone.utc),
    )


async def test_sqlite_snapshot_removed_between_lookup_and_link():
    snapshot_id, *_ = await seed_snapshots()
    async with db.session_scope() as session:
        assert session.get_bind().dialect.name == "sqlite"
        incident_id = await _create_incident(session)

        async def load_then_remove(conn, source):
            link = await reference_snapshot(conn, source)
            assert isinstance(link, IncidentSnapshot)
            await conn.execute(delete(IncidentTimelineManualSnapshot).where(
                IncidentTimelineManualSnapshot.id == snapshot_id,
            ))
            return link

        links = await add_links(
            session, incident_id, IncidentSnapshot, [snapshot_id], load_then_remove,
            "tester", datetime.now(timezone.utc),
        )
        assert links.added == 0
        assert [entry.result for entry in links.results] == ["not_found"]


async def _wait_for_snapshot_table_lock(task: asyncio.Task, mode: str, *, granted: bool) -> None:
    # フィクスチャが作ったスキーマの表だけを調べる。各問い合わせの間に他のタスクが進む。
    query = text("""
        SELECT EXISTS (
            SELECT 1 FROM pg_locks
            WHERE locktype = 'relation' AND relation = to_regclass('incident_snapshots')
              AND mode = :mode AND granted = :granted
        )
    """)
    try:
        async with asyncio.timeout(10), db.session_scope() as observer:
            while not task.done():
                if await observer.scalar(query, {"mode": mode, "granted": granted}):
                    return
    except TimeoutError:
        pytest.fail(f"Timed out waiting for incident_snapshots {mode} (granted={granted})")
    pytest.fail(f"Task finished before incident_snapshots {mode} (granted={granted}) was observed")


@pytest.mark.parametrize("incident_db", ["postgres"], indirect=True)
async def test_incident_postgres_snapshot_purge_waits_for_link(incident_db):
    snapshot_id, _, _ = await seed_snapshots()
    async with db.session_scope() as session:
        incident_id = await _create_incident(session)
    settings = Settings(
        incident_timeline_snapshot_retention_days=90, incident_timeline_snapshot_result_retention_days=7,
    )

    async with asyncio.timeout(30), asyncio.TaskGroup() as tasks:
        async with db.session_scope() as link_session:
            links = await _link_snapshot(link_session, incident_id, snapshot_id)
            assert links.added == 1
            purge_task = tasks.create_task(purge_retention(settings))
            await _wait_for_snapshot_table_lock(purge_task, "ShareLock", granted=False)
        await purge_task

    async with db.session_scope() as session:
        snapshot = IncidentTimelineManualSnapshot
        # 未紐付けの 2 行が消えたことも見て、ジョブがロールバックしていないと確かめる。
        assert (await session.execute(select(snapshot.id, snapshot.result_payload.is_not(None)))).all() == [
            (snapshot_id, True),
        ]
        assert await session.scalar(select(IncidentSnapshot.snapshot_id).where(
            IncidentSnapshot.incident_id == incident_id,
        )) == snapshot_id


@pytest.mark.parametrize("incident_db", ["postgres"], indirect=True)
async def test_incident_postgres_snapshot_link_waits_for_result_purge(incident_db):
    snapshot_id, blocker_id, _ = await seed_snapshots()
    async with db.session_scope() as session:
        incident_id = await _create_incident(session)
    settings = Settings(
        incident_timeline_snapshot_retention_days=0, incident_timeline_snapshot_result_retention_days=7,
    )

    async def link_snapshot() -> LinkBatch:
        async with db.session_scope() as session:
            return await _link_snapshot(session, incident_id, snapshot_id)

    snapshot = IncidentTimelineManualSnapshot
    async with asyncio.timeout(30), asyncio.TaskGroup() as tasks:
        async with db.session_scope() as blocker:
            # 別のスナップショットを押さえ、purge を結果の UPDATE で止める。
            assert await blocker.scalar(select(snapshot.id).where(snapshot.id == blocker_id).with_for_update()) == blocker_id
            purge_task = tasks.create_task(purge_retention(settings))
            await _wait_for_snapshot_table_lock(purge_task, "ShareLock", granted=True)
            link_task = tasks.create_task(link_snapshot())
            await _wait_for_snapshot_table_lock(link_task, "RowExclusiveLock", granted=False)
        await purge_task
        links = await link_task

    assert [link.result for link in links.results] == ["no_result"]
    assert links.added == 0
    async with db.session_scope() as session:
        assert await session.scalar(
            select(snapshot.result_payload.is_not(None)).where(snapshot.id == snapshot_id)
        ) is False
        assert await session.scalar(select(IncidentSnapshot.id).where(IncidentSnapshot.incident_id == incident_id)) is None


@pytest.mark.parametrize("incident_db", ["postgres"], indirect=True)
async def test_incident_postgres_purge_skips_when_advisory_lock_is_held(incident_db):
    snapshot_id, _, _ = await seed_snapshots()
    async with db.session_scope() as session:
        incident_id = await _create_incident(session)
        expired = datetime.now(timezone.utc) - timedelta(days=100)
        await session.execute(update(Incident).where(Incident.id == incident_id).values(
            status="resolved", resolved_at=expired,
        ))

    settings = Settings(
        incident_retention_days=90,
        incident_timeline_snapshot_retention_days=90,
        incident_timeline_snapshot_result_retention_days=7,
    )
    async with asyncio.timeout(30):
        async with db.session_scope() as holder:
            assert await holder.scalar(
                text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": PURGE_RETENTION_LOCK_KEY}
            )
            await purge_retention(settings)
        async with db.session_scope() as session:
            assert await session.get(Incident, incident_id) is not None
            snapshot = IncidentTimelineManualSnapshot
            assert await session.scalar(
                select(snapshot.result_payload.is_not(None)).where(snapshot.id == snapshot_id)
            ) is True

        await purge_retention(settings)
        async with db.session_scope() as session:
            assert await session.get(Incident, incident_id) is None
            assert await session.get(IncidentTimelineManualSnapshot, snapshot_id) is None


async def test_incident_snapshot_purge_lock_emits_no_sql_on_sqlite():
    engine = db.get_engine().sync_engine
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        async with db.session_scope() as session:
            await lock_incident_snapshot_links_for_purge(session)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert statements == []
