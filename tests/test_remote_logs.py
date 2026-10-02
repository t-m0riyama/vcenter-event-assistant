from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import select

from vcenter_event_assistant_plugin_api import (
    CollectionBatch,
    CollectorManifest,
    LogRecordInput,
)
from vcenter_event_assistant_plugin_api.validation import check_batch, check_manifest
from vcenter_event_assistant_plugin_api.testing import StubCollector
from vcenter_event_assistant.db.models import (
    CollectorRunState,
    IngestionState,
    LogRecord,
    VCenter,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.plugins.config import CollectorConfig
from vcenter_event_assistant.plugins.registry import CollectorRegistration
from vcenter_event_assistant.plugins.runtime import run_collector_for_vcenter
from vcenter_event_assistant.plugins.wire import batch_from_json, batch_to_json
from vcenter_event_assistant.services.ingestion import purge_old_logs
from vcenter_event_assistant.settings import Settings

NOW = datetime.now(timezone.utc)
MANIFEST = CollectorManifest("test.logs", "Logs", "1", data_kinds=frozenset({"log"}))


def log(**kwargs):
    return LogRecordInput(
        **dict(
            dict(
                source_id="esxi-1",
                host="esxi.local",
                log_kind="vmkernel",
                file_generation="generation-1",
                byte_offset=0,
                collected_at=NOW,
                occurred_at=NOW,
                severity="error",
                message="Storage ERROR 100%",
            ),
            **kwargs,
        )
    )


async def target():
    async with session_scope() as session:
        vc = VCenter(
            id=uuid.uuid4(), name="Logs VC", host="vc.local", username="u", password="p"
        )
        session.add(vc)
        await session.flush()
        return vc.id


def registration(batch):
    return CollectorRegistration(
        "test.logs",
        StubCollector(MANIFEST, batches=[batch]),
        "test",
        CollectorConfig(True, 60),
        "enabled",
    )


def test_log_wire_and_contract_are_backward_compatible():
    batch = CollectionBatch((), (), "position", (log(),))
    assert batch_from_json(batch_to_json(batch)) == batch
    assert batch_from_json(
        {"events": [], "metrics": [], "next_cursor": "old"}
    ) == CollectionBatch((), (), "old")
    assert not check_manifest(MANIFEST)
    assert not check_batch(MANIFEST, batch)
    assert (
        check_batch(
            CollectorManifest(
                "test.events", "Events", "1", data_kinds=frozenset({"event"})
            ),
            batch,
        )[0].code
        == "undeclared_log_kind"
    )


@pytest.mark.parametrize(
    "bad",
    [
        log(collected_at=NOW.replace(tzinfo=None)),
        log(byte_offset=-1),
        log(source_id=""),
        log(severity="x" * 65),
    ],
)
def test_invalid_log_contract_is_rejected(bad):
    assert any(
        i.severity == "error"
        for i in check_batch(MANIFEST, CollectionBatch(logs=(bad,)))
    )


async def test_log_retries_deduplicate_and_cursor_commits_atomically():
    vc = await target()
    reg = registration(CollectionBatch(logs=(log(), log()), next_cursor="cursor-1"))
    result = await run_collector_for_vcenter(Settings(), reg, vc)
    assert result.status == "ok" and result.logs_inserted == 1
    result = await run_collector_for_vcenter(Settings(), reg, vc)
    assert result.logs_inserted == 0
    async with session_scope() as session:
        assert len((await session.execute(select(LogRecord))).scalars().all()) == 1
        assert (
            await session.execute(select(IngestionState))
        ).scalar_one().cursor_value == "cursor-1"
        assert (
            await session.execute(select(CollectorRunState))
        ).scalar_one().logs_inserted == 0


async def test_database_failure_rolls_back_logs_and_cursor(monkeypatch):
    vc = await target()
    reg = registration(
        CollectionBatch(logs=(log(), log(byte_offset=100)), next_cursor="cursor-2")
    )
    from vcenter_event_assistant.plugins import runtime

    original = runtime._insert_on_conflict_do_nothing
    calls = 0

    async def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected DB failure")
        return await original(*args, **kwargs)

    monkeypatch.setattr(runtime, "_insert_on_conflict_do_nothing", fail_second)
    assert (await run_collector_for_vcenter(Settings(), reg, vc)).status == "failed"
    async with session_scope() as session:
        assert not (await session.execute(select(LogRecord))).scalars().all()
        assert not (await session.execute(select(IngestionState))).scalars().all()
        assert (
            await session.execute(select(CollectorRunState))
        ).scalar_one().status == "failed"


async def test_search_filters_pagination_unparsed_time_and_retention(client):
    vc = await target()
    old = NOW - timedelta(days=8)
    batch = CollectionBatch(
        logs=(
            log(),
            log(byte_offset=100, occurred_at=None, message="Unknown clock"),
            log(byte_offset=200, occurred_at=old, message="Expired"),
        )
    )
    assert (
        await run_collector_for_vcenter(Settings(), registration(batch), vc)
    ).logs_inserted == 3
    response = await client.get(
        "/api/logs",
        params={
            "vcenter_id": str(vc),
            "message_contains": "100%",
            "source_id": "esxi-1",
            "log_kind": "vmkernel",
            "severity": "error",
        },
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    response = await client.get(
        "/api/logs",
        params={
            "from": NOW.isoformat(),
            "to": NOW.isoformat(),
            "limit": 1,
            "offset": 1,
        },
    )
    assert response.json()["total"] == 2
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["effective_at"].endswith("Z")
    assert (await client.get("/api/logs", params={"limit": 201})).status_code == 422
    assert (
        await client.get(
            "/api/logs", params={"from": NOW.isoformat(), "to": old.isoformat()}
        )
    ).status_code == 400
    async with session_scope() as session:
        assert (
            await purge_old_logs(session, settings=Settings(log_retention_days=7)) == 1
        )
    assert (await client.get("/api/logs")).json()["total"] == 2
