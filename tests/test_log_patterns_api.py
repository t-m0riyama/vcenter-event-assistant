"""ログの型の一覧、タイムラインと保存・出力の契約を確かめる。"""

import csv
import io
import itertools
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from vcenter_event_assistant.db import session as db
from vcenter_event_assistant.db.models import (
    Base,
    IncidentTimelineManualSnapshot,
    LogPattern,
    LogPatternBackfillState,
    LogPatternBaseline,
    LogRecord,
    VCenter,
)
from vcenter_event_assistant.services.log_patterns import timeline as pattern_timeline
from vcenter_event_assistant.services.log_patterns.masking import MASK_VERSION
from vcenter_event_assistant.settings import get_settings

START = datetime(2026, 11, 24, tzinfo=timezone.utc)
END = START + timedelta(hours=1)
BOUNDS = {"from": START.isoformat(), "to": END.isoformat()}
PATTERNS = "/api/logs/patterns"
TIMELINE = "/api/incident-timeline"
POSITIONS = itertools.count(1)


@pytest.fixture(params=["sqlite", "postgres"])
async def pattern_db(request, monkeypatch):
    if request.param == "sqlite":
        yield
        return
    url = os.environ.get("VEA_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("VEA_TEST_POSTGRES_URL must point to a dedicated test DB")
    schema = f"log_pattern_api_{uuid4().hex}"
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        with monkeypatch.context() as patch:
            patch.setattr(db, "_session_factory", async_sessionmaker(engine, expire_on_commit=False))
            yield
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await admin.dispose()


def vc(name):
    return VCenter(id=uuid4(), name=name, host="vc.example", username="u", password="p")


def log(center, key, *, version=MASK_VERSION, at=START, severity=" Warn ", source="source", host="esx"):
    return LogRecord(
        vcenter_id=center.id, collector_id="test.logs", source_id=source, host=host,
        log_kind="Hostd", file_generation="g", byte_offset=next(POSITIONS), effective_at=at,
        collected_at=at, severity=severity, message=f"Log {key}", pattern_key=key,
        pattern_version=version,
    )


def pattern(center, key, *, at=START, source="source", template=None):
    return LogPattern(
        vcenter_id=center.id, pattern_key=key, pattern_version=MASK_VERSION, log_kind="hostd",
        template=template or f"Template {key}", first_seen_at=at - timedelta(days=1),
        last_seen_at=at, total_count=99, max_severity_rank=4,
        warning_first_seen_at=at, warning_first_source_id=source,
    )


def baseline(center, *, source="source", started_at=START - timedelta(days=3)):
    return LogPatternBaseline(
        vcenter_id=center.id, source_id=source, log_kind="hostd",
        pattern_version=MASK_VERSION, started_at=started_at,
    )


async def save(centers, *rows, completed=False):
    async with db.session_scope() as session:
        session.add_all(centers)
        await session.flush()
        session.add_all(rows)
        if completed:
            state = await session.get(LogPatternBackfillState, MASK_VERSION)
            if state is None:
                session.add(LogPatternBackfillState(
                    pattern_version=MASK_VERSION, upper_id=0, last_id=0, completed_at=START,
                ))
            else:
                state.completed_at = START


async def view(client, **options):
    response = await client.post(
        f"{TIMELINE}/view", json={**BOUNDS, "sources": ["log"], **options},
    )
    assert response.status_code == 200, response.text
    return response.json()["highlights"]


async def test_log_pattern_grouping(pattern_db, open_client):
    a, b = vc("A"), vc("B")
    await save(
        [a, b], pattern(a, "shared"), pattern(b, "shared"),
        log(a, "shared", severity=None), log(a, "shared", at=END, severity=" CRIT "),
        log(b, "shared", severity=" Err "), log(a, None), log(b, "missing"),
        log(a, "shared", version=MASK_VERSION + 1), log(b, "shared", version=None),
        log(a, "shared", at=END + timedelta(seconds=1)),
    )
    async with open_client("viewer") as client:
        response = await client.get(PATTERNS, params=BOUNDS)
        assert response.status_code == 200, response.text
        result = response.json()
        assert (result["total"], result["truncated"], result["pending_count"]) == (2, False, 4)
        first, second = result["items"]
        assert first == {
            "vcenter_id": str(a.id), "vcenter_name": "A", "pattern_key": "shared",
            "log_kind": "hostd", "template": "Template shared", "count": 2,
            "first_utc": "2026-11-24T00:00:00Z", "last_utc": "2026-11-24T01:00:00Z",
            "max_severity_rank": 4, "first_seen_at": "2026-11-23T00:00:00Z",
        }
        assert (second["vcenter_id"], second["count"], second["max_severity_rank"]) == (str(b.id), 1, 3)
        filtered = await client.get(PATTERNS, params={
            **BOUNDS, "vcenter_id": str(a.id), "source_id": "source", "log_kind": "Hostd",
            "severity": " CRIT ", "message_contains": "LOG SHARED",
        })
        assert (filtered.json()["items"][0]["count"], filtered.json()["pending_count"]) == (1, 0)
    async with open_client(None) as client:
        assert (await client.get(PATTERNS, params=BOUNDS)).status_code == 401


async def test_log_pattern_scan_limit_and_required_window(pattern_db, open_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "log_pattern_scan_max_rows", 1)
    center = vc("A")
    await save([center], log(center, None), log(center, "missing", source="other"))
    async with open_client("viewer") as client:
        for field in BOUNDS:
            response = await client.get(PATTERNS, params={field: BOUNDS[field]})
            assert response.status_code == 422
            assert response.json()["detail"][0]["type"] == "missing"
        exceeded = await client.get(PATTERNS, params=BOUNDS)
        assert exceeded.status_code == 422
        assert exceeded.json()["detail"] == {
            "code": "log_pattern_scan_limit",
            "message": "対象のログが多すぎて集計できません。期間を短くするか、条件を追加して絞り込んでください。",
        }
        reversed_window = await client.get(PATTERNS, params={"from": END.isoformat(), "to": START.isoformat()})
        assert reversed_window.status_code == 400
        accepted = await client.get(PATTERNS, params={**BOUNDS, "source_id": "other"})
    assert accepted.status_code == 200
    assert accepted.json() == {"items": [], "total": 0, "truncated": False, "pending_count": 1}


async def test_log_pattern_group_limit(pattern_db, open_client):
    center = vc("A")
    keys = [f"{i:032x}" for i in range(201)]
    await save([center], *(pattern(center, key) for key in keys), *(log(center, key) for key in keys))
    async with open_client("viewer") as client:
        response = await client.get(PATTERNS, params=BOUNDS)
    result = response.json()
    assert (result["total"], result["truncated"], result["pending_count"]) == (201, True, 0)
    assert [item["pattern_key"] for item in result["items"]] == keys[:200]


async def test_log_pattern_key_filters_list_and_csv(pattern_db, open_client):
    center = vc("A")
    await save([center], log(center, "wanted"), log(center, "other"), log(center, None))
    params = {"pattern_key": "wanted", "vcenter_id": str(center.id)}
    async with open_client("viewer") as client:
        listed = await client.get("/api/logs", params=params)
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["message"] == "Log wanted"
        exported = await client.get("/api/logs/export.csv", params=params)
    assert exported.status_code == 200
    (row,) = csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig")))
    assert row["message"] == "Log wanted"


async def test_log_pattern_backfill_pending_and_source_omitted(viewer_client):
    assert (await view(viewer_client, sources=["event"]))["new_log_patterns"] is None
    highlights = await view(viewer_client)
    assert highlights["new_log_patterns"] == []
    assert highlights["log_patterns_backfill_pending"] is True
    response = await viewer_client.post(
        f"{TIMELINE}/export", params={"format": "md"}, json={**BOUNDS, "sources": ["log"]},
    )
    assert "埋め戻し中" in response.text


async def test_log_pattern_timeline_scope_and_order(pattern_db, open_client):
    a, b = vc("A"), vc("B")
    later = START + timedelta(minutes=3)
    excluded = [
        pattern(a, "info"), pattern(a, "unparsed", template="<UNPARSED>"),
        pattern(a, "before", at=START - timedelta(seconds=1)), pattern(a, "end", at=END),
        pattern(a, "stale"), pattern(a, "warm", source="warm"), pattern(a, "missing", source="unknown"),
    ]
    await save(
        [a, b], baseline(a), baseline(b), baseline(a, source="warm", started_at=START),
        pattern(a, "pair"), pattern(b, "pair"), pattern(a, "b"), pattern(a, "a"),
        pattern(a, "first"), *excluded,
        log(a, "pair", host="esx"), log(a, "pair", host="esx-long", severity=" ERROR ", at=later),
        log(a, "pair", severity="info"), log(a, "pair", at=END, severity="panic"),
        log(b, "pair", severity=" EMERG "), log(a, "b", severity=" ERROR ", at=later),
        log(a, "a", severity=" Err ", at=later), log(a, "first", severity="error"),
        log(a, "info", severity="notice"), log(a, "unparsed"), log(a, "before"), log(a, "end", at=END),
        log(a, "stale", version=MASK_VERSION + 1), log(a, "warm", source="warm", host="esx-warm"),
        log(a, "missing", source="unknown", host="esx-unknown"), completed=True,
    )
    async with open_client("viewer") as client:
        highlights = await view(client, anchor=START.isoformat())
        items = highlights["new_log_patterns"]
        assert [(item["vcenter_name"], item["pattern_key"]) for item in items] == [
            ("B", "pair"), ("A", "first"), ("A", "pair"), ("A", "a"), ("A", "b"),
        ]
        assert highlights["new_log_patterns_total"] == 5
        pair = items[2]
        assert (pair["count"], pair["hosts"], pair["max_severity_rank"]) == (2, ["esx", "esx-long"], 3)
        assert pair["first_seen_at"] == "2026-11-23T00:00:00Z"
        assert pair["warning_first_seen_at"] == "2026-11-24T00:00:00Z"
        warmups = {entry["source_id"]: entry for entry in highlights["log_patterns_warming_up"]}
        assert set(warmups) == {"unknown", "warm"}
        assert warmups["warm"] == {
            "vcenter_id": str(a.id), "vcenter_name": "A", "source_id": "warm",
            "host": "esx-warm", "log_kind": "hostd", "warmup_ends_at": "2026-11-27T00:00:00Z",
        }
        assert warmups["unknown"]["warmup_ends_at"] is None
        filtered = await view(client, vcenter_id=str(a.id), entity="ESX")
        assert filtered["new_log_patterns_total"] == 4
        exact = await view(client, vcenter_id=str(a.id), entity="ESX", entity_moid="host-1")
        assert next(item for item in exact["new_log_patterns"] if item["pattern_key"] == "pair")["count"] == 1
        assert exact["log_patterns_warming_up"] == []
        moid_only = await view(client, vcenter_id=str(a.id), entity_moid="host-1")
        assert moid_only["new_log_patterns"] == []
        assert moid_only["log_patterns_warming_up"] == []


async def test_log_pattern_timeline_limits_and_report(pattern_db, open_client, monkeypatch):
    monkeypatch.setattr(pattern_timeline, "utcnow", lambda: START + timedelta(days=8))
    center = vc("A")
    keys = [f"{i:032x}" for i in range(501)]
    warmup_sources = [f"warm-{i:02d}" for i in range(21)]
    await save(
        [center], baseline(center), *(pattern(center, key) for key in keys),
        *(log(center, key) for key in keys),
        *(log(center, keys[0], host=host) for host in ["z", "B", "a", "A"]),
        *(pattern(center, source, source=source) for source in warmup_sources),
        *(log(center, source, source=source) for source in warmup_sources),
        completed=True,
    )
    async with db.session_scope() as session:
        await session.execute(update(LogPattern).where(LogPattern.pattern_key == keys[0]).values(
            template="`html`\n### [link](https://example.invalid)",
        ))
    async with open_client("viewer") as client:
        highlights = await view(client)
        assert highlights["new_log_patterns_total"] == 501
        assert [item["pattern_key"] for item in highlights["new_log_patterns"]] == keys[:10]
        assert highlights["new_log_patterns"][0]["hosts"] == ["A", "B", "a"]
        assert highlights["new_log_patterns"][0]["count"] == 5
        assert len(highlights["log_patterns_warming_up"]) == 20
        assert highlights["log_patterns_warming_up_total"] == 21
        response = await client.post(
            f"{TIMELINE}/export", params={"format": "zip"}, json={**BOUNDS, "sources": ["log"]},
        )
    assert response.status_code == 200, response.text
    with ZipFile(io.BytesIO(response.content)) as archive:
        report = archive.read("report.md").decode()
        assert "### 初めて警告以上で出たログの型" in report
        assert "`` `html` ### [link](https://example.invalid) ``" in report
        assert "\n### [link]" not in report
        assert "最大重大度 warning" in report
        assert "ほかに 1 件" in report
        assert "ログの保持期間で行が削除された型は、一覧に出ないことがあります。" in report
        exported = json.loads(archive.read("result.json"))["highlights"]
        assert exported["log_patterns_warming_up_total"] == 21
        assert exported["new_log_patterns_out_of_retention"] is True
        assert exported["new_log_patterns"] == highlights["new_log_patterns"]


async def test_log_pattern_legacy_snapshot(viewer_client):
    sid = uuid4()
    await save([], IncidentTimelineManualSnapshot(
        id=sid, from_time=START, to_time=END, timestamp_utc=START, operator_note="保存済み",
        result_payload={
            "from_utc": START.isoformat(), "to_utc": END.isoformat(), "bucket_seconds": 60,
            "items": [], "overview": [], "truncated": False, "total_items": 0, "highlights": {},
        },
    ))
    path = f"{TIMELINE}/snapshots/manual/{sid}"
    response = await viewer_client.get(path)
    assert response.status_code == 200
    highlights = response.json()["result"]["highlights"]
    assert highlights["new_log_patterns"] is None
    assert highlights["new_log_patterns_total"] == 0
    assert highlights["log_patterns_backfill_pending"] is False
    assert highlights["log_patterns_warming_up"] == []
    assert highlights["log_patterns_warming_up_total"] == 0
    assert highlights["new_log_patterns_out_of_retention"] is False
    report = await viewer_client.get(f"{path}/export", params={"format": "md"})
    assert (
        "### 初めて警告以上で出たログの型\n\n"
        "判定していません（この機能の前に保存した結果、または種別にログが無い）"
    ) in report.text


async def test_log_pattern_manual_snapshot_round_trip(operator_client):
    center = vc("A")
    await save(
        [center], baseline(center), pattern(center, "ready"), log(center, "ready", severity=" ERR "),
        pattern(center, "warming", source="new-source"), log(center, "warming", source="new-source"),
        completed=True,
    )
    snapshots = f"{TIMELINE}/snapshots/manual"
    saved = await operator_client.post(snapshots, json={
        **BOUNDS, "timestamp_utc": START.isoformat(), "operator_note": "ログの型の判定を保存",
        "view_request": {**BOUNDS, "sources": ["log"]},
    })
    assert saved.status_code == 201, saved.text
    path = f"{snapshots}/{saved.json()['snapshot_id']}"
    detail = await operator_client.get(path)
    assert detail.status_code == 200, detail.text
    highlights = detail.json()["result"]["highlights"]
    assert [item["pattern_key"] for item in highlights["new_log_patterns"]] == ["ready"]
    assert [source["source_id"] for source in highlights["log_patterns_warming_up"]] == ["new-source"]
    assert highlights["log_patterns_warming_up_total"] == 1

    report = await operator_client.get(f"{path}/export", params={"format": "md"})
    assert report.status_code == 200, report.text
    assert "### 初めて警告以上で出たログの型" in report.text
    assert "Template ready" in report.text
    assert "最大重大度 error" in report.text
    assert "ほかに" not in report.text
