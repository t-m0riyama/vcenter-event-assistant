"""イベントの対象を取り込み、重複排除と削除を行う経路を確かめる。"""

import json
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pyVmomi import vim
from sqlalchemy import Uuid, bindparam, delete, func, select, text
from vcenter_event_assistant_plugin_api import (
    CollectionBatch,
    CollectionContext,
    CollectorManifest,
    EventEntityInput,
    EventInput,
)

from vcenter_event_assistant.db.models import EventEntity, EventRecord, IngestionState, VCenter
from vcenter_event_assistant.db.session import init_db, reset_db, session_scope
from vcenter_event_assistant.plugins.config import CollectorConfig
from vcenter_event_assistant.plugins.registry import (
    CollectorRegistration,
    build_collector_registry,
    set_collector_registry,
)
from vcenter_event_assistant.plugins.runtime import run_collector_for_vcenter
from vcenter_event_assistant.plugins.wire import batch_from_json, batch_to_json
from vcenter_event_assistant.services.ingest_runner import run_ingest_events
from vcenter_event_assistant.services.ingestion import ingest_events_for_vcenter, purge_old_events
from vcenter_event_assistant.settings import get_settings


class BatchCollector:
    manifest = CollectorManifest(
        id="test.event-entities",
        display_name="Test events",
        version="1.0.0",
        data_kinds=frozenset({"event"}),
    )
    batch = CollectionBatch()

    async def collect(self, context: CollectionContext) -> CollectionBatch:
        return self.batch


def _event(key, *entities, **fields):
    return EventInput(
        datetime.now(timezone.utc), "VmMigratedEvent", "Migrated", key,
        entities=entities, **fields,
    )


async def _new_vcenter(settings):
    async with session_scope(settings=settings) as session:
        vcenter = VCenter(name=f"entity-test-{uuid4()}", host="vc.example", username="u", password="p")
        session.add(vcenter)
        await session.flush()
        return vcenter.id


async def _saved_entities(settings, vcenter_id):
    async with session_scope(settings=settings) as session:
        result = await session.execute(
            text("""SELECT e.vmware_key, t.role, t.position, t.is_primary,
                           t.entity_moid, t.entity_name, t.entity_type
                    FROM event_entities AS t JOIN events AS e ON t.event_id = e.id
                    WHERE e.vcenter_id = :id AND t.vcenter_id = e.vcenter_id
                    ORDER BY e.vmware_key, t.role, t.position""")
            .bindparams(bindparam("id", type_=Uuid())),
            {"id": vcenter_id},
        )
        return result.all()


@pytest.fixture(params=["sqlite", "postgres"])
async def event_db(request):
    settings = get_settings().model_copy(update={"mock_mode": False})
    if request.param == "postgres":
        url = os.environ.get("VEA_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("VEA_TEST_POSTGRES_URL must point to a dedicated test DB")
        settings = settings.model_copy(update={"database_url": url})
        await reset_db()
        await init_db(settings=settings)

    vcenter_id = await _new_vcenter(settings)
    try:
        yield settings, vcenter_id
    finally:
        async with session_scope(settings=settings) as session:
            await session.execute(delete(VCenter).where(VCenter.id == vcenter_id))
        if request.param == "postgres":
            await reset_db()


@pytest.fixture
def entity_db(event_db):
    settings, vcenter_id = event_db
    plugin = BatchCollector()
    registration = CollectorRegistration(
        plugin.manifest.id, plugin, "test", CollectorConfig(True, 300), "enabled"
    )

    async def ingest(*events, next_cursor=None):
        plugin.batch = CollectionBatch(events=events, next_cursor=next_cursor)
        result = await run_collector_for_vcenter(settings, registration, vcenter_id)
        assert result.status == "ok", result.error
        return result.events_inserted

    return settings, vcenter_id, ingest


@pytest.mark.asyncio
async def test_event_entities_deduplicate_replays_and_cascade(entity_db):
    settings, vcenter_id, ingest = entity_db
    old = replace(
        _event(1, EventEntityInput("vm", is_primary=True, entity_moid="vm-old")),
        occurred_at=datetime.now(timezone.utc) - timedelta(days=settings.event_retention_days + 1),
    )
    recent = _event(
        2, EventEntityInput("vm", is_primary=True, entity_moid="vm-first"),
        entity_moid="vm-event-column", entity_name="event column", entity_type="VirtualMachine",
    )
    duplicate = _event(2, EventEntityInput("host", is_primary=True, entity_moid="host-duplicate"))
    empty = _event(3, entity_moid="vm-no-children")
    assert await ingest(old, recent, duplicate, empty) == 3
    assert await ingest(duplicate, old, empty) == 0
    assert [row[:5] for row in await _saved_entities(settings, vcenter_id)] == [
        (1, "vm", 0, True, "vm-old"),
        (2, "vm", 0, True, "vm-first"),
    ]

    event_rows = select(EventRecord.vmware_key).where(
        EventRecord.vcenter_id == vcenter_id,
        EventRecord.collector_id == BatchCollector.manifest.id,
    ).order_by(EventRecord.vmware_key)
    # JOIN では、親が消えた孤立行を検出できない。
    count_entities = select(func.count(EventEntity.id)).where(EventEntity.vcenter_id == vcenter_id)
    async with session_scope(settings=settings) as session:
        assert await session.scalar(
            select(EventRecord.entity_moid).where(
                EventRecord.vcenter_id == vcenter_id,
                EventRecord.collector_id == BatchCollector.manifest.id,
                EventRecord.vmware_key == 2,
            )
        ) == "vm-event-column"

        # 共有 DB でも、この試験の保持期間削除を他の vCenter に残さない。
        async with session.begin_nested() as purge:
            await purge_old_events(session, settings=settings)
            assert (await session.scalars(event_rows)).all() == [2, 3]
            assert await session.scalar(count_entities) == 1
            await purge.rollback()

        assert await session.scalar(count_entities) == 2
        await session.execute(delete(VCenter).where(VCenter.id == vcenter_id))
        assert await session.scalar(count_entities) == 0


@pytest.mark.asyncio
async def test_large_event_entity_batch(entity_db):
    settings, vcenter_id, ingest = entity_db
    entities = tuple(EventEntityInput("vm", position=i, is_primary=i == 0) for i in range(4))
    assert await ingest(*(_event(i, *entities) for i in range(10_000))) == 10_000
    assert len(await _saved_entities(settings, vcenter_id)) == 40_000


@pytest.mark.asyncio
async def test_invalid_event_entities_are_sanitized(entity_db, caplog):
    settings, vcenter_id, ingest = entity_db
    long_name = "n" * 1025
    invalid = _event(
        1,
        EventEntityInput("sourceHost", entity_moid="match", is_primary=True),
        EventEntityInput("host", entity_moid="match", is_primary=True),
        EventEntityInput("vm", entity_moid="match", entity_name=long_name, entity_type="t" * 257),
        EventEntityInput("vm", entity_moid="duplicate", entity_name="discard"),
        EventEntityInput("", is_primary=True),
        EventEntityInput("r" * 65, is_primary=True),
        EventEntityInput("ds", entity_moid="m" * 257),
        entity_moid="match",
    )
    fallback = _event(
        2,
        EventEntityInput("sourceHost", entity_name="same"),
        EventEntityInput("host", 2, entity_name="same"),
        EventEntityInput("host", 1, entity_name="same"),
        entity_moid="m" * 257, entity_name="same",
    )
    unmatched = _event(
        3, EventEntityInput("vm", entity_name="same"),
        entity_moid="different", entity_name="same",
    )
    assert await ingest(invalid, fallback, unmatched) == 3
    assert "role" in caplog.text
    assert await _saved_entities(settings, vcenter_id) == [
        (1, "ds", 0, False, None, None, None),
        (1, "host", 0, False, "match", None, None),
        (1, "sourceHost", 0, False, "match", None, None),
        (1, "vm", 0, True, "match", "n" * 1023 + "…", None),
        (2, "host", 1, True, None, "same", None),
        (2, "host", 2, False, None, "same", None),
        (2, "sourceHost", 0, False, None, "same", None),
        (3, "vm", 0, False, None, "same", None),
    ]
    async with session_scope(settings=settings) as session:
        result = await session.execute(
            select(EventRecord.entity_moid, EventRecord.entity_name).where(
                EventRecord.vcenter_id == vcenter_id,
                EventRecord.collector_id == BatchCollector.manifest.id,
                EventRecord.vmware_key == 2,
            )
        )
        assert result.one() == (None, "same")


@pytest.mark.asyncio
async def test_event_entities_with_invalid_types_do_not_block_cursor(entity_db, caplog):
    settings, vcenter_id, ingest = entity_db
    assert await ingest(_event(1), next_cursor="previous") == 1
    invalid = _event(
        2,
        EventEntityInput(123),
        EventEntityInput(["host"]),
        EventEntityInput("host", position=True),
        EventEntityInput("host", position=-1),
        EventEntityInput("host", position=2**31),
        EventEntityInput("host", position="2"),
        EventEntityInput("host", position={}),
        EventEntityInput("host", position=1.0),
        EventEntityInput(
            "vm", is_primary="true", entity_type=123, entity_moid={}, entity_name=["name"],
        ),
        EventEntityInput("host", position=2**31 - 1, is_primary=0, entity_moid="host-1"),
    )
    assert await ingest(invalid, _event(3), next_cursor="advanced") == 2
    assert await _saved_entities(settings, vcenter_id) == [
        (2, "host", 2**31 - 1, False, "host-1", None, None),
        (2, "vm", 0, True, None, None, None),
    ]
    warnings = [
        record.getMessage() for record in caplog.records
        if record.name == "vcenter_event_assistant.services.ingestion" and record.levelname == "WARNING"
    ]
    assert len(warnings) == 8
    async with session_scope(settings=settings) as session:
        assert await session.scalar(
            select(IngestionState.cursor_value).where(
                IngestionState.vcenter_id == vcenter_id,
                IngestionState.kind == BatchCollector.manifest.id,
            )
        ) == "advanced"


@pytest.mark.asyncio
async def test_builtin_ingestion_stores_all_vm_migration_event_entities(
    event_db, monkeypatch, no_external_collectors,
):
    settings, vcenter_id = event_db

    async def list_test_vcenter(session):
        vcenter = await session.get(VCenter, vcenter_id)
        assert vcenter is not None and vcenter.is_enabled
        return [vcenter]

    monkeypatch.setattr("vcenter_event_assistant.services.ingest_runner.list_enabled_vcenters", list_test_vcenter)
    event = vim.event.VmMigratedEvent(
        key=51, createdTime=datetime.now(timezone.utc), fullFormattedMessage="Migrated",
        vm=vim.event.VmEventArgument(name="vm", vm=vim.VirtualMachine("vm-51")),
        host=vim.event.HostEventArgument(name="dest", host=vim.HostSystem("host-2")),
        sourceHost=vim.event.HostEventArgument(name="source", host=vim.HostSystem("host-1")),
        sourceDatastore=vim.event.DatastoreEventArgument(name="ds", datastore=vim.Datastore("ds-1")),
        datacenter=vim.event.DatacenterEventArgument(name="dc", datacenter=vim.Datacenter("dc-1")),
        computeResource=vim.event.ComputeResourceEventArgument(
            name="cluster", computeResource=vim.ClusterComputeResource("domain-c1"),
        ),
        sourceDatacenter=vim.event.DatacenterEventArgument(
            name="source dc", datacenter=vim.Datacenter("dc-2"),
        ),
    )
    si = MagicMock()
    collector = si.RetrieveContent.return_value.eventManager.CreateCollectorForEvents.return_value
    collector.ReadNextEvents.side_effect = [[event], []]
    monkeypatch.setattr("vcenter_event_assistant.plugins.runtime.connect_vcenter", lambda **_: si)
    monkeypatch.setattr("vcenter_event_assistant.plugins.runtime.disconnect", lambda _: None)
    set_collector_registry(build_collector_registry(settings))
    try:
        assert await run_ingest_events(settings) == 1
    finally:
        set_collector_registry(None)

    async with session_scope(settings=settings) as session:
        assert await session.scalar(
            select(EventRecord.entity_moid).where(EventRecord.vcenter_id == vcenter_id)
        ) == "vm-51"
    assert [row[1:5] for row in await _saved_entities(settings, vcenter_id)] == [
        ("computeResource", 0, False, "domain-c1"),
        ("datacenter", 0, False, "dc-1"),
        ("host", 0, False, "host-2"),
        ("sourceDatacenter", 0, False, "dc-2"),
        ("sourceDatastore", 0, False, "ds-1"),
        ("sourceHost", 0, False, "host-1"),
        ("vm", 0, True, "vm-51"),
    ]


@pytest.mark.asyncio
async def test_legacy_ingestion_stores_event_entities_and_counts_only_new_events(event_db, monkeypatch):
    settings, vcenter_id = event_db
    now = datetime.now(timezone.utc)
    row = {
        "occurred_at": now, "event_type": "VmMigratedEvent", "message": "Migrated", "vmware_key": 1,
        "entity_moid": "vm-1", "entities": (EventEntityInput("vm", entity_moid="vm-1", is_primary=True),),
    }
    monkeypatch.setattr("vcenter_event_assistant.services.ingestion.fetch_events_blocking", lambda **_: ([row], now))
    async with session_scope(settings=settings) as session:
        vcenter = await session.get(VCenter, vcenter_id)
        assert await ingest_events_for_vcenter(session, vcenter, settings=settings) == 1
        assert await ingest_events_for_vcenter(session, vcenter, settings=settings) == 0
        assert await session.scalar(
            select(EventRecord.entity_moid).where(EventRecord.vcenter_id == vcenter_id)
        ) == "vm-1"

    assert [saved[:5] for saved in await _saved_entities(settings, vcenter_id)] == [
        (1, "vm", 0, True, "vm-1"),
    ]


def test_event_entities_wire_round_trip_and_legacy_defaults():
    child = EventEntityInput("vm", 2, "VirtualMachine", "vm-5", "vm-name", True)
    batch = CollectionBatch(events=(_event(5, child, EventEntityInput("host"), entity_moid="vm-5"),))
    wire = json.loads(json.dumps(batch_to_json(batch)))
    assert batch_from_json(wire) == batch

    del wire["events"][0]["entity_moid"]
    del wire["events"][0]["entities"]
    old_event, = batch_from_json(wire).events
    assert old_event.entity_moid is None
    assert old_event.entities == ()


@pytest.mark.parametrize(
    ("entities", "expected"),
    [
        (None, ()),
        (
            [{"role": "vm", "entity_moid": "vm-5", "future_field": "ignored"}, {"position": 2}],
            (EventEntityInput("vm", entity_moid="vm-5"),),
        ),
    ],
)
def test_event_entities_wire_accepts_optional_and_future_fields(entities, expected):
    wire = batch_to_json(CollectionBatch(events=(_event(5),)))
    wire["events"][0]["entities"] = entities
    event, = batch_from_json(wire).events
    assert event.entities == expected
