"""インシデント API の編集、権限、写しと経過を検証する。"""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event as sql_event, text, update
from sqlalchemy.engine import Engine

from vcenter_event_assistant.db.models import (
    AlertHistory,
    AlertRule,
    EventEntity,
    EventRecord,
    IncidentTimelineManualSnapshot,
    User,
    VCenter,
)
from vcenter_event_assistant.db.session import get_engine, session_scope

pytestmark = pytest.mark.asyncio
ROOT = "/api/incidents"
AT = datetime(2026, 11, 25, 1, 2, 3, 123456, tzinfo=timezone.utc)


async def test_incident_edit_revision_and_roles(client, viewer_client, operator_client):
    async with session_scope() as session:
        await session.execute(update(User).where(User.username == "test-operator").values(display_name="担当者"))

    created = await operator_client.post(ROOT, json={
        "title": "100%_Storage", "status": "resolved", "level": "warning",
        "assignee": "担当", "summary": "要約", "started_at": AT.isoformat(),
    })
    assert created.status_code == 201
    incident = created.json()["incident"]
    assert incident["resolved_at"].endswith("Z")
    assert incident["started_at"] == "2026-11-25T01:02:03.123456Z"
    assert incident["created_by"] == incident["updated_by"] == "担当者（test-operator）"
    path = f"{ROOT}/{incident['id']}"
    assert (await viewer_client.get(path)).json() == incident
    assert (await viewer_client.get(ROOT)).json() == {"items": [], "total": 0}
    page = (await viewer_client.get(ROOT, params=[("status", "open"), ("status", "resolved"), ("q", "%_sto")])).json()
    assert page["total"] == 1
    assert "summary" not in page["items"][0]
    assert (await viewer_client.get(ROOT, params={"status": "resolved", "q": "100_"})).json()["total"] == 0
    assert (await viewer_client.post(ROOT, json={"title": "権限なし"})).status_code == 403
    assert (await viewer_client.patch(path, json={"revision": incident["revision"]})).status_code == 403
    assert (await operator_client.delete(path)).status_code == 403

    unchanged = (await operator_client.patch(path, json={
        "revision": incident["revision"], "status": "resolved",
    })).json()
    assert unchanged["revision"] == incident["revision"]
    assert unchanged["resolved_at"] == incident["resolved_at"]
    assert unchanged["updated_at"] == incident["updated_at"]
    changed = (await operator_client.patch(path, json={
        "revision": incident["revision"], "level": None, "summary": None,
        "started_at": None, "status": "monitoring", "title": "更新後",
    })).json()
    assert changed["revision"] != incident["revision"]
    assert changed["assignee"] == "担当"
    assert changed["summary"] == ""
    assert all(changed[field] is None for field in ("level", "started_at", "resolved_at"))
    assert len(changed["entries"]) == 1
    assert changed["entries"][0]["kind"] == "change"
    assert "100%_Storage" in changed["entries"][0]["body"]
    assert "要約を更新しました" in changed["entries"][0]["body"]

    stale = await operator_client.patch(path, json={"revision": incident["revision"], "title": "古い編集"})
    assert stale.status_code == 409
    assert stale.headers["X-VEA-Error-Code"] == "incident_stale"
    assert (await operator_client.patch(path, json={"revision": changed["revision"], "title": None})).status_code == 422
    resolved = (await operator_client.patch(path, json={"revision": changed["revision"], "status": "resolved"})).json()
    assert resolved["resolved_at"] != incident["resolved_at"]
    assert (await client.delete(path)).status_code == 204
    assert (await client.patch(path, json={"revision": resolved["revision"]})).status_code == 404
    assert (await client.get(f"{ROOT}/bad-id")).status_code == 404
    assert (await client.delete(f"{ROOT}/bad-id")).status_code == 404
    assert (await client.patch(f"{ROOT}/bad-id", json={"revision": resolved["revision"]})).status_code == 404


async def seed_sources(event_count=3):
    async with session_scope() as session:
        vc = VCenter(name="調査先", host="vc.example", username="u", password="p")
        rule = AlertRule(name="通知ルール", rule_type="event_score", config={})
        session.add_all([vc, rule])
        await session.flush()
        records = [
            EventRecord(vcenter_id=vc.id, vmware_key=i, occurred_at=AT, event_type="t",
                        message="本" * 2100, user_comment="注" * 2100)
            for i in range(event_count)
        ]
        history = AlertHistory(rule_id=rule.id, context_key="key", state="firing", channel="none", occurred_at=AT)
        snapshots = [
            IncidentTimelineManualSnapshot(from_time=AT, to_time=AT, timestamp_utc=AT, operator_note="保存"),
            IncidentTimelineManualSnapshot(from_time=AT, to_time=AT, timestamp_utc=AT, operator_note="保存", result_payload={}),
        ]
        session.add_all([*records, history, *snapshots])
        await session.flush()
        return [row.id for row in records], history.id, [str(row.id) for row in snapshots]


def timed(id):
    return {"id": id, "occurred_at": "2026-11-25T10:02:03.123456+09:00"}


async def test_incident_links_copy_data_and_validate_each_source(client, operator_client):
    events, history, snapshots = await seed_sources()
    no_result, saved = snapshots
    missing = str(uuid4())
    created = await client.post(ROOT, json={
        "title": "障害", "events": [timed(events[0]), {"id": events[0], "occurred_at": "2000-01-01T00:00:00Z"}],
        "alerts": [timed(history)], "snapshot_ids": [no_result, missing, saved],
    })
    assert created.status_code == 201
    data = created.json()
    incident = data["incident"]
    path = f"{ROOT}/{incident['id']}"
    assert [item["result"] for item in data["link_results"]["events"]] == ["added"]
    assert [item["result"] for item in data["link_results"]["alerts"]] == ["added"]
    assert [item["result"] for item in data["link_results"]["snapshots"]] == ["no_result", "not_found", "added"]
    assert incident["snapshots"][0]["operator_note"] == "保存"
    assert incident["snapshots"][0]["has_result"]
    assert len(incident["entries"]) == 1
    event = incident["events"][0]
    assert event["message"] == "本" * 2000
    assert event["user_comment"] == "注" * 2000
    assert event["source_exists"] and incident["alerts"][0]["source_exists"]
    assert event["vcenter_name"] == "調査先"
    assert incident["alerts"][0]["vcenter_name"] is None
    alert_path = f"{path}/alerts"
    event_path = f"{path}/events"
    for target in (event_path, alert_path):
        assert (await client.post(target, json={"items": [{"id": 1}]})).status_code == 422
        assert (await client.post(target, json={"items": [timed(1)] * 101})).status_code == 422
    assert (await client.post(f"{path}/snapshots", json={"snapshot_ids": [saved] * 101})).status_code == 422
    assert (await client.post(f"{path}/snapshots", json={"snapshot_ids": ["bad-id"]})).status_code == 422

    linked = await operator_client.post(event_path, json={"items": [
        timed(events[0]),
        {"id": events[1], "occurred_at": "2026-11-25T01:02:03.123455Z"},
        {"id": events[2], "occurred_from": "2026-11-25T01:02:03.123457Z", "occurred_to": "2026-11-26T00:00:00Z"},
        timed(999999),
    ]})
    assert linked.json() == {"added": 0, "results": [
        {"id": events[0], "result": "already_linked", "link_id": event["id"]},
        *[{"id": i, "result": "not_found"} for i in (*events[1:3], 999999)],
    ]}
    assert (await client.get(path)).json() == incident
    page = (await client.get(ROOT)).json()
    assert [page["items"][0][f"{kind}_count"] for kind in ("event", "alert", "snapshot")] == [1, 1, 1]

    async with session_scope() as session:
        await session.execute(delete(EventRecord).where(EventRecord.id == events[0]))
        await session.execute(delete(AlertHistory).where(AlertHistory.id == history))
        session.add(EventRecord(id=events[0], vcenter_id=UUID(event["vcenter_id"]),
            vmware_key=99999, event_type="別", occurred_at=AT))

    detail = (await client.get(path)).json()
    assert detail["events"] == [{**event, "source_exists": False}]
    assert detail["alerts"] == [{**incident["alerts"][0], "source_exists": False}]
    assert detail["revision"] == incident["revision"]


async def test_incident_event_link_limit_and_inclusive_range(client):
    events, _, _ = await seed_sources(event_count=502)
    created = (await client.post(ROOT, json={"title": "上限"})).json()["incident"]
    detail_path = f"{ROOT}/{created['id']}"
    path = f"{detail_path}/events"
    for start in range(0, 400, 100):
        response = await client.post(path, json={"items": [timed(i) for i in events[start:start + 100]]})
        assert response.json()["added"] == 100
    last = await client.post(path, json={"items": [
        {"id": events[400], "occurred_from": AT.isoformat(), "occurred_to": AT.isoformat()},
        *[timed(i) for i in events[401:499]],
    ]})
    assert last.json()["added"] == 99
    response = await client.post(path, json={"items": [timed(i) for i in events[499:]]})
    assert response.json()["added"] == 1
    assert [item["result"] for item in response.json()["results"]] == ["added", "limit_exceeded", "limit_exceeded"]

    before = (await client.get(detail_path)).json()
    duplicate = await client.post(path, json={"items": [timed(events[0]), timed(events[-1]), timed(999999)]})
    assert duplicate.json() == {"added": 0, "results": [
        {"id": events[0], "result": "already_linked", "link_id": before["events"][0]["id"]},
        {"id": events[-1], "result": "limit_exceeded"},
        {"id": 999999, "result": "not_found"},
    ]}
    assert (await client.get(detail_path)).json() == before


async def test_incident_entry_limit_soft_delete_and_unlink(client, operator_client):
    from vcenter_event_assistant.db.models import IncidentEntry

    _, _, snapshots = await seed_sources()
    incident = (await client.post(ROOT, json={"title": "メモ", "snapshot_ids": [snapshots[1]]})).json()["incident"]
    path = f"{ROOT}/{incident['id']}"
    notes = f"{path}/entries"
    new = await operator_client.post(notes, json={"body": "秘密"})
    assert new.status_code == 201
    entry = new.json()
    assert entry["kind"] == "note"
    assert (await operator_client.delete(f"{notes}/{entry['id']}")).status_code == 403
    assert (await client.delete(f"{notes}/{entry['id']}")).status_code == 204
    assert (await client.delete(f"{notes}/{incident['entries'][0]['id']}")).status_code == 204
    detail = (await client.get(path)).json()
    deleted = detail["entries"][1]
    assert deleted["body"] == ""
    assert deleted["author"] == entry["author"]
    assert deleted["deleted_by"] == "test-admin" and deleted["deleted_at"]
    assert detail["revision"] == incident["revision"]
    async with session_scope() as session:
        session.add_all([
            IncidentEntry(incident_id=UUID(incident["id"]), kind="note", body="追加",
                          author="test-admin", created_at=datetime.now(timezone.utc) - timedelta(days=1))
            for _ in range(999)
        ])
    overflow = await operator_client.post(notes, json={"body": "上限"})
    assert overflow.status_code == 409
    assert overflow.headers["X-VEA-Error-Code"] == "incident_entry_limit"
    link_id = incident["snapshots"][0]["id"]
    another = (await client.post(ROOT, json={"title": "別件"})).json()["incident"]
    assert (await operator_client.delete(f"{ROOT}/{another['id']}/snapshots/{link_id}")).status_code == 404
    assert (await operator_client.delete(f"{path}/snapshots/{link_id}")).status_code == 204
    patched = await operator_client.patch(path, json={"revision": incident["revision"], "status": "resolved"})
    assert patched.status_code == 200
    assert patched.json()["snapshots"] == []
    assert [entry["kind"] for entry in patched.json()["entries"][-2:]] == ["link", "change"]


@pytest.mark.parametrize("incident_db", ["postgres"], indirect=True)
async def test_incident_postgres_snapshot_savepoint(incident_db, open_client, monkeypatch):
    from vcenter_event_assistant.api.routes import incidents
    from vcenter_event_assistant.services.incidents import reference_snapshot

    async with session_scope() as session:
        rows = [
            IncidentTimelineManualSnapshot(from_time=AT, to_time=AT, timestamp_utc=AT,
                                           operator_note="", result_payload={})
            for _ in range(3)
        ]
        session.add_all(rows)
        await session.flush()
        existing, removed, next_snapshot = [row.id for row in rows]

    async def remove_after_read(session, id):
        link = await reference_snapshot(session, id)
        if id == removed:
            async with session_scope() as concurrent:
                await concurrent.execute(delete(IncidentTimelineManualSnapshot).where(
                    IncidentTimelineManualSnapshot.id == removed,
                ))
        return link

    async with open_client() as client:
        created = await client.post(ROOT, json={"title": "紐付け", "snapshot_ids": [str(existing)]})
        assert created.status_code == 201
        path = f"{ROOT}/{created.json()['incident']['id']}/snapshots"
        monkeypatch.setattr(incidents, "reference_snapshot", remove_after_read)
        response = await client.post(path, json={
            "snapshot_ids": [str(existing), str(existing), str(removed), str(next_snapshot)],
        })
        assert response.status_code == 200
        assert [item["result"] for item in response.json()["results"]] == ["already_linked", "not_found", "added"]
        assert response.json()["added"] == 1


async def test_incident_alert_copy_batches_targets_and_tracks_legacy_timestamp(client):
    async with session_scope() as session:
        vc = VCenter(name="調査先", host="vc.example", username="u", password="p")
        rule = AlertRule(name="障害パターン", rule_type="event_pattern", config={})
        session.add_all([vc, rule])
        await session.flush()
        event = EventRecord(
            vcenter_id=vc.id, vmware_key=1, event_type="t", occurred_at=AT,
            entities=[EventEntity(
                vcenter_id=vc.id, entity_moid="host-1", entity_name="ホスト名", entity_type="HostSystem",
                position=0, role="host", is_primary=True,
            )],
        )
        alerts = [
            AlertHistory(rule_id=rule.id, context_key=f"{vc.id}:host-1:pattern-{index}", state="firing", channel="none")
            for index in (1, 2)
        ]
        session.add_all([event, *alerts])
        await session.flush()
        first, second = [alert.id for alert in alerts]
        await session.execute(text("UPDATE alert_history SET occurred_at = '2026-11-25 01:02:03' WHERE id = :id"),
                              [{"id": first}, {"id": second}])

    statements = []

    def track(conn, cursor, statement, parameters, context, executemany):
        if "WITH pattern_entity_probes" in statement or "FROM vcenters" in statement:
            statements.append(statement)

    sql_event.listen(Engine, "before_cursor_execute", track)
    try:
        response = await client.post(ROOT, json={
            "title": "通知",
            "alerts": [{"id": id, "occurred_at": "2026-11-25T01:02:03Z"} for id in (first, second)],
        })
    finally:
        sql_event.remove(Engine, "before_cursor_execute", track)
    assert response.status_code == 201
    assert len(statements) == 2
    links = response.json()["incident"]["alerts"]
    assert [link["alert_history_id"] for link in links] == [first, second]
    for link in links:
        assert link["entity_moid"] == "host-1"
        assert link["entity_name"] == "ホスト名"
        assert link["vcenter_name"] == "調査先"
        assert link["source_exists"]


@pytest.mark.parametrize("incident_db", ["sqlite", "postgres"], indirect=True)
async def test_incident_concurrent_patches_share_one_revision(incident_db, open_client):
    async with open_client() as client:
        created = await client.post(ROOT, json={"title": "更新前"})
        assert created.status_code == 201
        incident = created.json()["incident"]
        path = f"{ROOT}/{incident['id']}"
        responses = await asyncio.gather(*[
            client.patch(path, json={"revision": incident["revision"], "title": title})
            for title in ("更新 1", "更新 2")
        ])
        assert sorted(response.status_code for response in responses) == [200, 409]
        stale = next(response for response in responses if response.status_code == 409)
        assert stale.headers["X-VEA-Error-Code"] == "incident_stale"
        updated = (await client.get(path)).json()
        assert updated["title"] in {"更新 1", "更新 2"}
        [entry] = updated["entries"]
        assert entry["body"] == f"件名を「更新前」から「{updated['title']}」に変えました。"


async def test_incident_requests_reject_extra_fields_and_blank_notes(client):
    created = (await client.post(ROOT, json={"title": "入力検証"})).json()["incident"]
    path = f"{ROOT}/{created['id']}"
    requests = [
        ("POST", ROOT, {"title": "余分な項目", "updated_by": "別人"}),
        ("PATCH", path, {"revision": created["revision"], "titel": "誤記"}),
        ("POST", f"{path}/entries", {"body": "メモ", "author": "別人"}),
        ("POST", f"{path}/entries", {"body": " \t\n　 "}),
        ("POST", f"{path}/events", {"items": [], "event": "余分"}),
        ("POST", f"{path}/events", {"items": [{**timed(1), "message": "偽の写し"}]}),
        ("POST", f"{path}/alerts", {"items": [{**timed(1), "rule_name": "偽の写し"}]}),
        ("POST", f"{path}/snapshots", {"snapshot_ids": [], "snapshot": "余分"}),
    ]
    for method, url, body in requests:
        response = await client.request(method, url, json=body)
        assert response.status_code == 422, (method, url, body, response.text)
    assert (await client.get(path)).json() == created


async def test_incident_list_query_count_is_independent_of_page_size(client):
    events, history, snapshots = await seed_sources()
    for index in range(5):
        response = await client.post(ROOT, json={
            "title": f"障害 {index}", "events": [timed(events[0])],
            "alerts": [timed(history)], "snapshot_ids": [snapshots[1]],
        })
        assert response.status_code == 201

    statements = []
    engine = get_engine().sync_engine

    def track(conn, cursor, statement, parameters, context, executemany):
        sql = statement.lower()
        if sql.startswith("select") and "from incident" in sql:
            statements.append(sql)

    sql_event.listen(engine, "before_cursor_execute", track)
    try:
        one = await client.get(ROOT, params={"limit": 1})
        single = statements[:]
        statements.clear()
        many = await client.get(ROOT, params={"limit": 5})
    finally:
        sql_event.remove(engine, "before_cursor_execute", track)

    assert one.status_code == many.status_code == 200
    assert len(one.json()["items"]) == 1
    assert len(many.json()["items"]) == 5
    assert len(single) == len(statements) == 5
    assert sum("group by" in sql for sql in statements) == 3
    for item in many.json()["items"]:
        assert [item[f"{kind}_count"] for kind in ("event", "alert", "snapshot")] == [1, 1, 1]
