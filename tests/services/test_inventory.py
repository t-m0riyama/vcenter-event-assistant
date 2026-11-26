"""インベントリの観測・保持期間・定期収集の試験。"""

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from textwrap import dedent
from threading import Event

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from vcenter_event_assistant.collectors.inventory import (
    InventoryObjectData,
    InventoryObservation,
)
from vcenter_event_assistant.db.base import Base
from vcenter_event_assistant.db.models import (
    InventoryObject,
    InventoryRelation,
    InventorySyncRun,
    InventorySyncState,
    VCenter,
)
from vcenter_event_assistant.db.session import get_engine, session_scope
from vcenter_event_assistant.jobs.scheduler import purge_retention
from vcenter_event_assistant.services import inventory
from vcenter_event_assistant.settings_binding import require_settings


T0 = datetime(2026, 11, 20, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=10)
T2 = T1 + timedelta(minutes=10)
H1 = ("vm_host", "vm-1", "host-1")
H2 = ("vm_host", "vm-1", "host-2")
DS = ("host_datastore", "host-1", "ds-1")
NET = ("vm_network", "vm-1", "network-1")
OBJECTS = {
    "vm-1": InventoryObjectData("VirtualMachine", "vm"),
    "host-1": InventoryObjectData("HostSystem", "esx1"),
    "host-2": InventoryObjectData("HostSystem", "esx2"),
    "ds-1": InventoryObjectData("Datastore", "ds"),
    "network-1": InventoryObjectData("Network", "network"),
}


@pytest.fixture(autouse=True)
def open_inventory_reads(monkeypatch):
    monkeypatch.setattr(inventory, "_reads_closed", False)


def observation(*relations, objects=None, carry=(), instance="vc-1"):
    return InventoryObservation(
        instance, OBJECTS if objects is None else objects, set(relations), set(carry)
    )


def center(name="inventory", enabled=True):
    return VCenter(
        name=name, host="vc.example", username="u", password="p", is_enabled=enabled
    )


async def save(session, vc, data, t):
    await inventory.persist_inventory(session, vc, data, observed_at=t, started_at=t)
    await session.commit()


async def relations(session, vc):
    return (
        await session.scalars(
            select(InventoryRelation)
            .where(InventoryRelation.vcenter_id == vc)
            .order_by(InventoryRelation.id)
            .execution_options(populate_existing=True)
        )
    ).all()


def open_edges(rows):
    return {(r.kind, r.child_moid, r.parent_moid) for r in rows if r.valid_to is None}


def utc(value):
    return value.replace(tzinfo=timezone.utc)


@pytest.fixture(params=["sqlite", "postgres"])
async def inventory_session(request, tmp_path):
    if request.param == "postgres":
        url = os.environ.get("VEA_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("VEA_TEST_POSTGRES_URL must point to a dedicated test DB")
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'inventory.db'}"
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            if request.param == "postgres":
                from sqlalchemy import text

                await conn.execute(text("DROP SCHEMA public CASCADE"))
                await conn.execute(text("CREATE SCHEMA public"))
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


async def test_inventory_inserts_closes_and_reopens_on_each_dialect(inventory_session):
    session = inventory_session
    vc = center()
    session.add(vc)
    await session.commit()
    await save(session, vc.id, observation(H1, DS), T0)
    await save(session, vc.id, observation(H2, DS), T1)
    await save(session, vc.id, observation(H1, DS), T2)
    rows = await relations(session, vc.id)
    assert open_edges(rows) == {H1, DS}
    assert sorted(
        (utc(r.valid_from), utc(r.valid_to) if r.valid_to else None)
        for r in rows
        if r.kind == "vm_host"
    ) == [(T0, T1), (T1, T2), (T2, None)]
    assert [utc(r.valid_from) for r in rows if r.kind == "host_datastore"] == [T0]
    state = await session.get(InventorySyncState, vc.id)
    assert utc(state.first_success_at) == T0
    assert utc(state.last_success_at) == T2
    assert state.object_count == 5 and state.relation_count == 2
    assert await session.scalar(select(func.count()).select_from(InventorySyncRun)) == 3

    for end in (None, T0):
        async with session.begin_nested() as transaction:
            session.add(
                InventoryRelation(
                    vcenter_id=vc.id,
                    kind="vm_host",
                    child_moid="vm-1",
                    parent_moid="host-1",
                    valid_from=T2,
                    valid_to=end,
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
            await transaction.rollback()


@pytest.fixture
async def vcenter_id():
    async with session_scope() as session:
        vc = center()
        session.add(vc)
        await session.flush()
        return vc.id


@pytest.fixture
async def inventory_vcenter_id(inventory_session):
    vc = center()
    inventory_session.add(vc)
    await inventory_session.commit()
    return vc.id


async def test_inventory_instance_reset_preserves_removal_and_resets_first_seen(
    inventory_session, inventory_vcenter_id, caplog
):
    session, vc = inventory_session, inventory_vcenter_id
    await save(session, vc, observation(H1, DS), T0)
    active = {key: OBJECTS[key] for key in ("host-1", "vm-1")}
    await save(session, vc, observation(H1, objects=active), T1)
    reset = {**active, "ds-1": OBJECTS["ds-1"]}
    await save(session, vc, observation(H1, DS, objects=reset, instance="new"), T2)
    assert (
        f"inventory instance changed vcenter_id={vc} old_instance_uuid=vc-1 new_instance_uuid=new"
        in caplog.text
    )
    objects = {row.moid: row for row in await session.scalars(select(InventoryObject))}
    assert utc(objects["network-1"].removed_at) == T1
    assert utc(objects["network-1"].first_seen_at) == T0
    for moid in reset:
        assert objects[moid].removed_at is None
        assert utc(objects[moid].first_seen_at) == T2

    reappeared_at = T2 + timedelta(minutes=10)
    await save(session, vc, observation(H1, DS, instance="new"), reappeared_at)
    assert objects["network-1"].removed_at is None
    assert utc(objects["network-1"].first_seen_at) == reappeared_at


async def test_inventory_carries_only_visible_edges_and_restores_template(
    inventory_session, inventory_vcenter_id
):
    session = inventory_session
    vcenter_id = inventory_vcenter_id
    await save(session, vcenter_id, observation(H1, DS, NET), T0)
    objects = {moid: obj for moid, obj in OBJECTS.items() if moid != "network-1"}
    await save(
        session,
        vcenter_id,
        observation(H2, objects=objects, carry=[DS[:2], NET[:2]]),
        T1,
    )
    assert open_edges(await relations(session, vcenter_id)) == {H2, DS}
    template_objects = {moid: obj for moid, obj in objects.items() if moid != "vm-1"}
    await save(session, vcenter_id, observation(DS, objects=template_objects), T2)
    assert open_edges(await relations(session, vcenter_id)) == {DS}
    vm = await session.scalar(
        select(InventoryObject).where(InventoryObject.moid == "vm-1")
    )
    assert utc(vm.removed_at) == T2
    await save(session, vcenter_id, observation(H2, DS), T2 + timedelta(minutes=10))
    await session.refresh(vm)
    assert vm.removed_at is None
    assert utc(vm.first_seen_at) == T0
    assert open_edges(await relations(session, vcenter_id)) == {H2, DS}


async def test_inventory_only_updates_changed_objects(vcenter_id):
    updates = []

    def collect_update(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE inventory_objects"):
            updates.extend(parameters if executemany else [parameters])

    engine = get_engine().sync_engine
    event.listen(engine, "before_cursor_execute", collect_update)
    try:
        async with session_scope() as session:
            await save(session, vcenter_id, observation(H1), T0)
            await save(session, vcenter_id, observation(H1), T1)
            assert updates == []
            renamed = {**OBJECTS, "vm-1": InventoryObjectData("VirtualMachine", "new")}
            await save(session, vcenter_id, observation(H1, objects=renamed), T2)
            assert len(updates) == 1
            vm = await session.scalar(
                select(InventoryObject).where(InventoryObject.moid == "vm-1")
            )
            assert vm.name == "new"
    finally:
        event.remove(engine, "before_cursor_execute", collect_update)


@pytest.mark.parametrize(
    "old,new,reset", [(None, "", False), ("", "", False), ("", "vc-2", True)]
)
async def test_inventory_clock_rollback_and_instance_change(
    inventory_session, inventory_vcenter_id, old, new, reset
):
    session = inventory_session
    vcenter_id = inventory_vcenter_id
    await save(session, vcenter_id, observation(H1, DS, instance=old or ""), T1)
    state = await session.get(InventorySyncState, vcenter_id)
    state.instance_uuid = old
    await session.commit()
    await save(session, vcenter_id, observation(H2, DS, instance=new), T0)
    rows = await relations(session, vcenter_id)
    assert open_edges(rows) == {H2, DS}
    assert all(utc(r.valid_to) == T1 for r in rows if r.valid_to)
    assert all(utc(r.valid_from) == T1 for r in rows)
    assert len(rows) == (4 if reset else 3)
    await session.refresh(state)
    assert utc(state.last_success_at) == T1
    assert state.instance_uuid == new
    await save(
        session, vcenter_id, observation(H2, instance="vc-3", carry=[DS[:2]]), T2
    )
    await session.refresh(state)
    assert utc(state.first_success_at) == T2
    assert open_edges(await relations(session, vcenter_id)) == {H2}


async def test_inventory_warning_survives_later_success(vcenter_id):
    async with session_scope() as session:
        await save(session, vcenter_id, observation(H1), T0)
        await save(
            session,
            vcenter_id,
            observation(H1, objects={key: OBJECTS[key] for key in ("vm-1", "host-1")}),
            T1,
        )
        state = await session.get(InventorySyncState, vcenter_id)
        warning = state.last_warning
        assert warning and utc(state.last_warning_at) == T1
        await save(session, vcenter_id, observation(H1), T2)
        await session.refresh(state)
        assert state.last_warning == warning and utc(state.last_warning_at) == T1


async def test_inventory_write_failure_rolls_back_and_records_separately(
    vcenter_id, monkeypatch
):
    async with session_scope() as session:
        await save(session, vcenter_id, observation(H1), T0)

    persist = inventory.persist_inventory

    async def fail_after_write(*args, **kwargs):
        await persist(*args, **kwargs)
        await args[0].flush()
        raise RuntimeError("secret from vCenter")

    monkeypatch.setattr(inventory, "persist_inventory", fail_after_write)
    monkeypatch.setattr(
        inventory,
        "read_vcenter_inventory",
        lambda *_, **__: observation(
            H2, objects={key: OBJECTS[key] for key in ("vm-1", "host-2")}
        ),
    )
    await inventory.sync_inventory(require_settings())
    async with session_scope() as session:
        state = await session.get(InventorySyncState, vcenter_id)
        assert utc(state.last_success_at) == T0
        assert state.last_failure_at is not None
        assert state.last_error == "RuntimeError: collector execution failed"
        assert (
            await session.scalar(select(func.count()).select_from(InventorySyncRun))
            == 1
        )
        assert open_edges(await relations(session, vcenter_id)) == {H1}
        assert (
            await session.scalar(
                select(func.count())
                .select_from(InventoryObject)
                .where(InventoryObject.removed_at.is_(None))
            )
            == 5
        )


async def test_inventory_timeout_advances_and_skips_unfinished_read(monkeypatch):
    async with session_scope() as session:
        first, second, disabled = center("a"), center("b"), center("c", enabled=False)
        session.add_all([first, second, disabled])
    entered = Event()
    release = Event()
    calls = []

    def read(vc, settings, *, after_relations):
        calls.append(vc.name)
        if vc.id == first.id:
            entered.set()
            release.wait(10)
        return observation(H1)

    monkeypatch.setattr(inventory, "read_vcenter_inventory", read)
    settings = require_settings().model_copy(
        update={"inventory_sync_timeout_seconds": 0.1}
    )
    try:
        await asyncio.wait_for(inventory.sync_inventory(settings), timeout=5)
        assert entered.is_set()
        async with session_scope() as session:
            slow = await session.get(InventorySyncState, first.id)
            assert slow.last_error.startswith("InventoryReadTimeout:")
        await asyncio.wait_for(inventory.sync_inventory(settings), timeout=5)
        assert calls == ["a", "b", "b"]
        async with session_scope() as session:
            slow = await session.get(InventorySyncState, first.id)
            fast = await session.get(InventorySyncState, second.id)
            assert (
                slow.last_error.startswith("InventoryReadStillRunning:")
                and slow.last_success_at is None
            )
            assert fast.last_success_at is not None
            assert await session.get(InventorySyncState, disabled.id) is None
    finally:
        release.set()
        for future in tuple(inventory._reads.values()):
            await asyncio.wait_for(asyncio.wrap_future(future), 5)


async def test_inventory_same_vcenter_reads_do_not_overlap(vcenter_id, monkeypatch):
    entered = Event()
    release = Event()
    calls = []

    def read(vc, settings, *, after_relations):
        calls.append(vc.id)
        entered.set()
        release.wait(10)
        return observation(H1)

    monkeypatch.setattr(inventory, "read_vcenter_inventory", read)
    settings = require_settings()
    first = asyncio.create_task(inventory.sync_inventory(settings))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        second = asyncio.create_task(inventory.sync_inventory(settings))
        await asyncio.sleep(0.05)
        assert calls == [vcenter_id]
        release.set()
        await asyncio.wait_for(asyncio.gather(first, second), timeout=5)
        assert calls == [vcenter_id, vcenter_id]
    finally:
        release.set()
        await first


async def test_inventory_deleted_vcenter_cascades_and_racing_read_records_nothing(
    vcenter_id, monkeypatch, caplog
):
    reading = Event()
    released = Event()

    def read(vc, settings, *, after_relations):
        reading.set()
        released.wait(10)
        return observation(H2)

    async with session_scope() as session:
        await save(session, vcenter_id, observation(H1), T0)

    monkeypatch.setattr(inventory, "read_vcenter_inventory", read)
    running = asyncio.create_task(inventory.sync_inventory(require_settings()))
    try:
        assert await asyncio.to_thread(reading.wait, 5)
        async with session_scope() as session:
            await session.delete(await session.get(VCenter, vcenter_id))
    finally:
        released.set()
        await asyncio.wait_for(running, timeout=5)
    assert "inventory sync target deleted" in caplog.text
    async with session_scope() as session:
        for model in (
            InventoryObject,
            InventoryRelation,
            InventorySyncRun,
            InventorySyncState,
        ):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_inventory_retention_preserves_current_and_cutoff_boundary(
    vcenter_id, monkeypatch
):
    cutoff = T1
    now = cutoff + timedelta(days=7)
    monkeypatch.setattr(inventory, "utcnow", lambda: now)
    async with session_scope() as session:
        await save(
            session, vcenter_id, observation(H1, DS, NET), T0 - timedelta(minutes=10)
        )
        await save(
            session,
            vcenter_id,
            observation(
                H2,
                NET,
                objects={key: value for key, value in OBJECTS.items() if key != "ds-1"},
            ),
            T0,
        )
        await save(
            session,
            vcenter_id,
            observation(
                H2,
                objects={
                    key: value
                    for key, value in OBJECTS.items()
                    if key not in {"ds-1", "network-1"}
                },
            ),
            cutoff,
        )
    settings = require_settings().model_copy(update={"event_retention_days": 7})
    await purge_retention(settings)
    async with session_scope() as session:
        rows = await relations(session, vcenter_id)
        assert {r.kind for r in rows} == {"vm_host", "vm_network"}
        assert open_edges(rows) == {H2}
        assert {
            o.moid for o in (await session.scalars(select(InventoryObject))).all()
        } == {"vm-1", "host-1", "host-2", "network-1"}
        runs = (await session.scalars(select(InventorySyncRun))).all()
        assert [utc(run.observed_at) for run in runs] == [cutoff]
        assert await session.get(InventorySyncState, vcenter_id) is not None


async def test_inventory_reference_name_missing_preserves_existing_name(vcenter_id):
    async with session_scope() as session:
        await save(session, vcenter_id, observation(H1), T0)
        missing_name = {
            **OBJECTS,
            "vm-1": InventoryObjectData("VirtualMachine", None),
            "host-new": InventoryObjectData("HostSystem", None),
        }
        await save(session, vcenter_id, observation(H1, objects=missing_name), T1)
        objects = {
            row.moid: row.name for row in await session.scalars(select(InventoryObject))
        }
        assert objects["vm-1"] == "vm"
        assert objects["host-new"] == "host-new"


@pytest.mark.parametrize(
    "read_fails, disconnect_fails", [(False, False), (False, True), (True, True)]
)
def test_inventory_vcenter_read_disconnects_once(
    monkeypatch, caplog, read_fails, disconnect_fails
):
    from unittest.mock import Mock

    si = Mock()
    connect = Mock(return_value=si)
    expected = observation(H1)
    read = Mock(
        return_value=expected,
        side_effect=ValueError("read failed") if read_fails else None,
    )
    disconnect = Mock(
        side_effect=RuntimeError("private response") if disconnect_fails else None
    )
    monkeypatch.setattr(inventory, "connect_vcenter", connect)
    monkeypatch.setattr(inventory, "read_inventory", read)
    monkeypatch.setattr(inventory, "disconnect", disconnect)

    settings = require_settings().model_copy(
        update={"inventory_sync_timeout_seconds": 60}
    )
    if read_fails:
        with pytest.raises(ValueError, match="read failed"):
            inventory.read_vcenter_inventory(center(), settings)
    else:
        assert inventory.read_vcenter_inventory(center(), settings) is expected
    assert connect.call_args.kwargs["http_connection_timeout"] == 60
    read.assert_called_once_with(si.RetrieveContent.return_value)
    disconnect.assert_called_once_with(si)
    if disconnect_fails:
        assert "inventory disconnect failed" in caplog.text
        assert "private response" not in caplog.text


async def test_inventory_pool_saturation_skips_without_submitting(monkeypatch):
    async with session_scope() as session:
        a, b, c = center("a"), center("b"), center("c")
        session.add_all([a, b, c])
    release = Event()
    started = []
    thread_class = inventory.Thread

    def inventory_thread(**kwargs):
        thread = thread_class(**kwargs)
        started.append(thread)
        return thread

    def read(vc, settings, *, after_relations):
        if vc.name != "c":
            release.wait(10)
        return observation(H1)

    monkeypatch.setattr(inventory, "Thread", inventory_thread)
    monkeypatch.setattr(inventory, "read_vcenter_inventory", read)
    settings = require_settings().model_copy(
        update={"inventory_sync_timeout_seconds": 0.15}
    )
    try:
        await asyncio.wait_for(inventory.sync_inventory(settings), timeout=5)
        assert len(started) == 2
        async with session_scope() as session:
            state = await session.get(InventorySyncState, c.id)
            assert (
                state.last_error
                == "InventoryWorkerUnavailable: 専用スレッドに空きがありません。"
            )
        inventory.shutdown_inventory_reads()
        inventory.start_inventory_reads()
        await asyncio.wait_for(inventory.sync_inventory(settings), timeout=5)
        assert len(started) == 2
    finally:
        release.set()
        for future in tuple(inventory._reads.values()):
            await asyncio.wait_for(asyncio.wrap_future(future), 5)

    await inventory.sync_inventory(settings)
    async with session_scope() as session:
        assert (await session.get(InventorySyncState, c.id)).last_success_at is not None


async def test_inventory_reads_are_closed_after_shutdown_and_reopen_with_lifespan(
    vcenter_id, monkeypatch
):
    from vcenter_event_assistant import main

    reads = []

    def read(vc, settings, *, after_relations):
        reads.append(vc.id)
        return observation(H1)

    async def skip_startup(*args, **kwargs):
        return None

    monkeypatch.setattr(main, "init_db", skip_startup)
    monkeypatch.setattr(main, "warn_invalid_vcenter_transports", skip_startup)
    monkeypatch.setattr(inventory, "read_vcenter_inventory", read)
    for _ in range(2):
        async with main.lifespan(main.create_app()):
            await asyncio.wait_for(inventory.sync_inventory(require_settings()), 5)
        await asyncio.wait_for(inventory.sync_inventory(require_settings()), 5)
        async with session_scope() as session:
            state = await session.get(InventorySyncState, vcenter_id)
            assert state.last_error.startswith("InventoryReadsClosed:")
    assert reads == [vcenter_id, vcenter_id]


def test_inventory_process_exits_with_stalled_read():
    script = dedent("""
        import asyncio
        from threading import Event
        from uuid import uuid4

        from vcenter_event_assistant.db.models import VCenter
        from vcenter_event_assistant.services import inventory
        from vcenter_event_assistant.settings import Settings

        entered = Event()

        def stalled_read(*args, **kwargs):
            entered.set()
            Event().wait()

        async def main():
            inventory.read_vcenter_inventory = stalled_read
            settings = Settings().model_copy(update={"inventory_sync_timeout_seconds": 0.25})
            try:
                await inventory._read_with_timeout(VCenter(id=uuid4()), settings)
            except inventory.InventoryReadTimeout:
                assert entered.is_set()
            else:
                raise AssertionError("読み取りがタイムアウトしなかった")
            inventory.shutdown_inventory_reads()
            print("shutdown complete", flush=True)

        asyncio.run(main())
    """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=8,
        check=True,
    )
    assert "shutdown complete" in result.stdout


async def test_inventory_job_logs_target_lookup_failure(monkeypatch, caplog):
    def fail(**kwargs):
        raise RuntimeError("target lookup failed")

    monkeypatch.setattr(inventory, "session_scope", fail)
    await inventory.sync_inventory(require_settings())
    assert "inventory sync job failed" in caplog.text


async def test_inventory_records_pyvmomi_wrapped_socket_timeout(
    vcenter_id, monkeypatch
):
    from pyVmomi import vim

    def connect(**kwargs):
        try:
            raise TimeoutError("private response")
        except TimeoutError as exc:
            raise vim.fault.HostConnectFault(msg=str(exc))

    monkeypatch.setattr(inventory, "connect_vcenter", connect)
    await inventory.sync_inventory(require_settings())
    async with session_scope() as session:
        state = await session.get(InventorySyncState, vcenter_id)
        assert (
            state.last_error == "InventoryReadTimeout: 読み取りがタイムアウトしました。"
        )
