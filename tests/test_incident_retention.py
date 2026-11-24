"""保持期間、CASCADE と PostgreSQL の SAVEPOINT を検証する。"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import func, select, update

from vcenter_event_assistant.db import session as db
from vcenter_event_assistant.db.models import IncidentTimelineManualSnapshot
from vcenter_event_assistant.jobs.scheduler import purge_retention
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
    from vcenter_event_assistant.db.models import Incident, IncidentEntry, IncidentSnapshot
    from vcenter_event_assistant.services.ingestion import purge_old_incident_timeline_snapshot_results

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

