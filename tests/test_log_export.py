import asyncio
import csv
import io
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, event, inspect

from vcenter_event_assistant.db.models import LogRecord, VCenter
from vcenter_event_assistant.db.session import (
    get_engine,
    get_session_factory,
    session_scope,
)
from vcenter_event_assistant.services import log_export

NOW = datetime(2026, 10, 3, 3, 34, 56, tzinfo=timezone.utc)


async def seed(count=5):
    vc = uuid.uuid4()
    async with session_scope() as session:
        session.add(
            VCenter(id=vc, name="Lab,東京", host="vc.local", username="u", password="p")
        )
        await session.flush()
        session.add_all([record(vc, i) for i in range(1, count + 1)])
    return vc


def record(vc, offset, **overrides):
    fields = dict(
        vcenter_id=vc,
        collector_id="test",
        source_id="esxi-1",
        host="esxi.local",
        log_kind="vmkernel",
        file_generation="one",
        byte_offset=offset,
        occurred_at=None,
        effective_at=NOW,
        collected_at=NOW,
        severity="error",
        message='日本語, "ERROR" 100%\n stack trace',
    )
    return LogRecord(**(fields | overrides))


def parse(data):
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline="")))


async def test_export_matches_list_filters_and_csv(client):
    vc = await seed()
    async with session_scope() as session:
        session.add(record(vc, 10, severity="info"))
        session.add(record(vc, 11, effective_at=NOW - timedelta(days=1)))
    params = dict(
        vcenter_id=str(vc),
        source_id="esxi-1",
        log_kind="vmkernel",
        severity="error",
        message_contains='error" 100%',
        **{"from": NOW.isoformat(), "to": NOW.isoformat()},
    )
    expected = (await client.get("/api/logs", params=params)).json()["items"]
    response = await client.get(
        "/api/logs/export.csv", params=params | {"time_zone": "Asia/Tokyo"}
    )
    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert response.content.endswith(b"\r\n")
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-accel-buffering"] == "no"
    assert 'attachment; filename="logs-' in response.headers["content-disposition"]
    rows = parse(response.content)
    assert [int(r["id"]) for r in rows] == [r["id"] for r in expected]
    assert len(rows) == 5
    assert list(rows[0]) == list(log_export.HEADER)
    assert rows[0]["effective_at"] == "2026/10/03 12:34:56"
    assert rows[0]["collected_at"] == "2026/10/03 12:34:56"
    assert rows[0]["occurred_at"] == ""
    assert rows[0]["vcenter_name"] == "Lab,東京"
    assert rows[0]["message"] == '日本語, "ERROR" 100%\n stack trace'
    assert rows[0]["time_zone"] == "Asia/Tokyo"
    assert rows[0]["utc_offset"] == "+09:00"


@pytest.mark.parametrize(
    "zone,instant,wall,offset",
    [
        ("UTC", NOW, "2026/10/03 03:34:56", "+00:00"),
        (
            "America/New_York",
            datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc),
            "2026/11/01 01:30:00",
            "-04:00",
        ),
        (
            "America/New_York",
            datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc),
            "2026/11/01 01:30:00",
            "-05:00",
        ),
    ],
)
async def test_time_zones_and_dst(client, zone, instant, wall, offset):
    vc = await seed(0)
    async with session_scope() as session:
        session.add(
            record(
                vc,
                1,
                effective_at=instant,
                occurred_at=instant,
                collected_at=instant,
                severity=None,
            )
        )
    response = await client.get("/api/logs/export.csv", params={"time_zone": zone})
    row = parse(response.content)[0]
    assert all(
        row[key] == wall for key in ("effective_at", "occurred_at", "collected_at")
    )
    assert row["utc_offset"] == offset
    assert row["severity"] == ""


async def test_empty_and_invalid_inputs(client):
    response = await client.get("/api/logs/export.csv")
    assert parse(response.content) == []
    assert response.content.decode("utf-8-sig") == ",".join(log_export.HEADER) + "\r\n"
    for zone in ("Invalid/Zone", "../UTC", ""):
        response = await client.get("/api/logs/export.csv", params={"time_zone": zone})
        assert response.status_code == 400
        assert "content-disposition" not in response.headers
    for path in ("/api/logs", "/api/logs/export.csv"):
        assert (
            await client.get(
                path,
                params={
                    "from": NOW.isoformat(),
                    "to": (NOW - timedelta(days=1)).isoformat(),
                },
            )
        ).status_code == 400
        assert (
            await client.get(path, params={"vcenter_id": "invalid"})
        ).status_code == 422
        assert (
            await client.get(path, params={"source_id": "x" * 129})
        ).status_code == 422
    assert (await client.get("/api/logs", params={"limit": 201})).status_code == 422


async def test_batches_exclude_insertions_allow_deletions_and_do_not_count(monkeypatch):
    monkeypatch.setattr(log_export, "BATCH_SIZE", 2)
    vc = await seed()
    factory = get_session_factory()
    queries = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement.lower())

    engine = get_engine().sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        upper, first = await log_export.prepare_log_export(factory, [])
        request = AsyncMock()
        request.is_disconnected.return_value = False
        stream = log_export.stream_log_csv(
            factory, [], ZoneInfo("UTC"), upper, first, request
        )
        data = await anext(stream)  # header
        data += await anext(stream)  # ids 5, 4; session already closed
        async with session_scope() as session:
            await session.execute(delete(LogRecord).where(LogRecord.id == 3))
            session.add(record(vc, 100, effective_at=NOW - timedelta(hours=1)))
            session.add(record(vc, 101, effective_at=NOW + timedelta(hours=1)))
        data += b"".join([chunk async for chunk in stream])
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert [int(r["id"]) for r in parse(data)] == [5, 4, 2, 1]
    reads = [q for q in queries if q.startswith("select")]
    assert not any("count(" in q for q in reads)
    # SQLite renders OFFSET 0 with LIMIT; no growing OFFSET is used.
    assert any("(log_records.effective_at, log_records.id) <" in q for q in reads)


async def test_disconnect_stops_before_next_read(monkeypatch):
    monkeypatch.setattr(log_export, "BATCH_SIZE", 2)
    await seed()
    factory = get_session_factory()
    upper, first = await log_export.prepare_log_export(factory, [])
    read = AsyncMock(side_effect=AssertionError("read after disconnect"))
    monkeypatch.setattr(log_export, "read_log_batch", read)
    request = AsyncMock()
    request.is_disconnected.side_effect = [False, False, True]
    stream = log_export.stream_log_csv(
        factory, [], ZoneInfo("UTC"), upper, first, request
    )
    chunks = [chunk async for chunk in stream]
    assert len(parse(b"".join(chunks))) == 2
    read.assert_not_called()


async def test_stream_failure_is_logged_and_raised(monkeypatch, caplog):
    monkeypatch.setattr(log_export, "BATCH_SIZE", 2)
    await seed()
    factory = get_session_factory()
    upper, first = await log_export.prepare_log_export(factory, [])
    monkeypatch.setattr(
        log_export,
        "read_log_batch",
        AsyncMock(side_effect=RuntimeError("DB unavailable")),
    )
    request = AsyncMock()
    request.is_disconnected.return_value = False
    stream = log_export.stream_log_csv(
        factory, [], ZoneInfo("UTC"), upper, first, request
    )
    with pytest.raises(RuntimeError, match="DB unavailable"):
        async for _ in stream:
            pass
    assert "Log CSV export failed after 2 rows" in caplog.text


async def test_first_read_failure_precedes_headers(client, monkeypatch):
    monkeypatch.setattr(
        log_export,
        "read_log_batch",
        AsyncMock(side_effect=RuntimeError("first read failed")),
    )
    with pytest.raises(RuntimeError, match="first read failed"):
        await client.get("/api/logs/export.csv")


async def test_cancelled_stream_propagates(monkeypatch):
    monkeypatch.setattr(log_export, "BATCH_SIZE", 2)
    await seed()
    factory = get_session_factory()
    upper, first = await log_export.prepare_log_export(factory, [])
    monkeypatch.setattr(
        log_export, "read_log_batch", AsyncMock(side_effect=asyncio.CancelledError())
    )
    request = AsyncMock()
    request.is_disconnected.return_value = False
    with pytest.raises(asyncio.CancelledError):
        async for _ in log_export.stream_log_csv(
            factory, [], ZoneInfo("UTC"), upper, first, request
        ):
            pass


async def test_export_index_exists():
    async with get_engine().connect() as conn:
        indexes = await conn.run_sync(lambda c: inspect(c).get_indexes("log_records"))
    assert any(
        i["name"] == "ix_log_effective_time_id"
        and i["column_names"] == ["effective_at", "id"]
        for i in indexes
    )


async def test_real_batch_boundary_releases_connection_before_every_chunk():
    await seed(2003)
    engine = get_engine().sync_engine
    active = 0

    def checkout(*args):
        nonlocal active
        active += 1

    def checkin(*args):
        nonlocal active
        active -= 1

    event.listen(engine, "checkout", checkout)
    event.listen(engine, "checkin", checkin)
    try:
        factory = get_session_factory()
        upper, first = await log_export.prepare_log_export(factory, [])
        assert len(first) == 2000
        assert active == 0
        request = AsyncMock()
        request.is_disconnected.return_value = False
        chunks = []
        async for chunk in log_export.stream_log_csv(
            factory, [], ZoneInfo("UTC"), upper, first, request
        ):
            assert active == 0
            chunks.append(chunk)
        assert [int(r["id"]) for r in parse(b"".join(chunks))] == list(
            range(2003, 0, -1)
        )
    finally:
        event.remove(engine, "checkout", checkout)
        event.remove(engine, "checkin", checkin)


def _log_row(**overrides):
    when = datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc)
    row = {
        "id": 1,
        "vcenter_id": uuid.UUID(int=1),
        "vcenter_name": "lab-vc",
        "source_id": "esxi-01",
        "host": "esxi-01.lab",
        "log_kind": "auth",
        "effective_at": when,
        "occurred_at": when,
        "collected_at": when,
        "severity": "info",
        "message": "hello",
        "file_generation": "gen-1",
        "byte_offset": 0,
    }
    row.update(overrides)
    return row


def _parse_csv_row(line: str) -> dict[str, str]:
    return dict(zip(log_export.HEADER, next(csv.reader(io.StringIO(line)))))


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_csv_row_neutralizes_formula_prefix(prefix):
    payload = f"{prefix}HYPERLINK(\"http://evil.example/\",\"x\")"
    line = log_export.csv_row(
        _log_row(
            message=payload,
            host=payload,
            source_id=payload,
            log_kind=payload,
            severity=payload,
            vcenter_name=payload,
            file_generation=payload,
        ),
        ZoneInfo("UTC"),
    )
    fields = _parse_csv_row(line)
    for key in ("message", "host", "source_id", "log_kind", "severity", "vcenter_name", "file_generation"):
        assert fields[key] == "'" + payload


def test_csv_row_keeps_plain_values_and_generated_columns():
    line = log_export.csv_row(_log_row(message="user root failed"), ZoneInfo("America/New_York"))
    fields = _parse_csv_row(line)
    assert fields["message"] == "user root failed"
    assert fields["host"] == "esxi-01.lab"
    # 生成した列（負のオフセット・数値）は無害化しない。
    assert fields["utc_offset"] == "-04:00"
    assert fields["byte_offset"] == "0"
    assert fields["id"] == "1"
