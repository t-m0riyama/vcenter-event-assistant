"""構成の観測・保存・定期収集を試験する。"""

import asyncio
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock, Mock

import pytest
from pyVmomi import vim, vmodl
from sqlalchemy import delete, event, select, update

from vcenter_event_assistant.auth.timeutil import as_utc
from vcenter_event_assistant.collectors import inventory_config as reader
from vcenter_event_assistant.collectors.config_values import VM_DETAIL_PATHS, value_hash
from vcenter_event_assistant.collectors.inventory import (
    InventoryObjectData,
    InventoryObservation,
)
from vcenter_event_assistant.collectors.inventory_config import (
    ConfigBaseline,
    ConfigObservation,
    PropertyRow,
    VMDetails,
)
from vcenter_event_assistant.db.models import (
    InventoryConfigDiff,
    InventoryConfigState,
    InventoryRelation,
    InventorySyncState,
    VCenter,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.jobs.scheduler import purge_retention
from vcenter_event_assistant.mocks.mock_inventory import (
    SCREENSHOT_HOSTS,
    SCREENSHOT_VCENTER_NAME,
    SCREENSHOT_VMS,
    mock_inventory,
    mock_inventory_config,
)
from vcenter_event_assistant.services import inventory
from vcenter_event_assistant.services.inventory_config import (
    config_baselines,
    persist_inventory_config,
)
from vcenter_event_assistant.settings import Settings
from vcenter_event_assistant.settings_binding import require_settings

T0 = datetime(2026, 11, 26, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=10)
T2 = T1 + timedelta(minutes=10)
T3 = T2 + timedelta(minutes=10)
BUILD = ("host", "host_build")
VM = ("vm", "vm_config")


@pytest.fixture(autouse=True)
def reads(monkeypatch):
    monkeypatch.setattr(inventory, "_reads", {})
    monkeypatch.setattr(inventory, "_reads_closed", False)


async def add_center(name="test"):
    async with session_scope() as session:
        center = VCenter(name=name, host="vc.example", username="test", password="test")
        session.add(center)
    return center


def _objects(values):
    types = {
        "host": "HostSystem",
        "vm": "VirtualMachine",
        "cluster": "ClusterComputeResource",
    }
    return {
        moid: InventoryObjectData(types[category.split("_")[0]], moid)
        for moid, category in values
    }


def snapshot(start, values, *, end=None, instance="instance"):
    return ConfigObservation(
        instance,
        start,
        end or start + timedelta(seconds=1),
        "configurationEx",
        objects=_objects(values),
        values=values,
    )


async def save(center, config):
    async with session_scope() as session:
        await persist_inventory_config(session, center.id, config)


async def stored(center):
    async with session_scope() as session:
        current = await session.scalars(
            select(InventoryConfigState).where(
                InventoryConfigState.vcenter_id == center.id
            )
        )
        diffs = await session.scalars(
            select(InventoryConfigDiff)
            .where(InventoryConfigDiff.vcenter_id == center.id)
            .order_by(InventoryConfigDiff.id)
        )
        status = await session.get(InventorySyncState, center.id)
        return {(row.moid, row.category): row for row in current}, list(diffs), status


@pytest.mark.parametrize("incident_db", ["sqlite", "postgres"], indirect=True)
async def test_config_diff_format_reset_verified_period_and_disappearance(incident_db):
    center = await add_center()
    await save(center, snapshot(T0, {BUILD: {"build": "1"}}))
    rows, diffs, state = await stored(center)
    assert not diffs
    assert rows[BUILD].format == 1
    assert as_utc(state.config_first_success_at) == T0 + timedelta(seconds=1)
    assert as_utc(rows[BUILD].verified_at) == T0
    assert rows[BUILD].value_hash == value_hash({"build": "1"})

    same = snapshot(T1, {BUILD: {"build": "1"}})
    same.objects["host"] = InventoryObjectData("HostSystem", "renamed")
    await save(center, same)
    rows, diffs, state = await stored(center)
    assert not diffs and as_utc(rows[BUILD].verified_at) == T1
    assert rows[BUILD].entity_name == "renamed"
    assert as_utc(state.config_first_success_at) == T0 + timedelta(seconds=1)
    async with session_scope() as session:
        await session.execute(update(InventoryConfigState).values(format=0))

    await save(center, snapshot(T2, {BUILD: {"build": "2"}}))
    rows, diffs, state = await stored(center)
    assert not diffs
    assert (rows[BUILD].format, rows[BUILD].value, as_utc(rows[BUILD].verified_at)) == (
        1,
        {"build": "2"},
        T2,
    )

    regressed = snapshot(T1, {BUILD: {"build": "3"}}, end=T1)
    regressed.objects["host"] = InventoryObjectData("HostSystem", "build changed")
    await save(center, regressed)
    rows, (diff,), state = await stored(center)
    assert (diff.old_value, diff.new_value, diff.entity_type, diff.entity_name) == (
        '"2"',
        '"3"',
        "HostSystem",
        "build changed",
    )
    assert as_utc(diff.changed_after) == as_utc(diff.observed_at) == T2
    assert as_utc(rows[BUILD].verified_at) == T2
    assert as_utc(state.config_last_started_at) == T1
    assert as_utc(state.config_last_success_at) == T2 + timedelta(seconds=1)

    await save(center, snapshot(T3, {}))
    rows, diffs, state = await stored(center)
    assert not rows
    assert state.config_object_count == 0
    await save(center, snapshot(T3, {BUILD: {"build": "return"}}))
    await save(
        center, snapshot(T3, {BUILD: {"build": "other instance"}}, instance="other")
    )
    rows, diffs, state = await stored(center)
    assert len(diffs) == 1
    assert rows[BUILD].value == {"build": "other instance"}
    assert state.config_instance_uuid == "other"
    assert as_utc(state.config_first_success_at) == as_utc(state.config_last_success_at)
    async with session_scope() as session:
        await session.execute(delete(VCenter).where(VCenter.id == center.id))
    assert await stored(center) == ({}, [], None)


def vm_props(cpu, version):
    return dict(
        zip(
            VM_DETAIL_PATHS,
            (
                version,
                cpu,
                1,
                4096,
                "vmx-21",
                "otherGuest64",
                Obj(),
                Obj(),
                [],
            ),
            strict=True,
        )
    )


@pytest.mark.parametrize(
    "mode",
    [
        "host-disconnected",
        "host-missing",
        "host-absent",
        "host-null",
        "vm-disconnected",
        "vm-version-missing",
        "vm-version-absent",
        "vm-version-null",
        "vm-detail-null",
        "vm-detail-missing",
        "vm-detail-absent",
        "vm-detail-removed",
        "vm-deferred",
    ],
)
@pytest.mark.parametrize("incident_db", ["sqlite", "postgres"], indirect=True)
async def test_config_diff_carry_over_leaves_last_verified_and_generation_for_next_read(
    mode, incident_db
):
    center = await add_center()
    is_vm = mode.startswith("vm-")
    key = VM if is_vm else BUILD
    ref = vim.VirtualMachine("vm") if is_vm else vim.HostSystem("host")
    version_path = "config.changeVersion"
    overview_path = version_path if is_vm else "summary.config.product"

    def observe(t, value, version, interruption=None, baselines=None):
        overview = {
            "name": "name",
            "runtime.connectionState": "connected",
            overview_path: version if is_vm else Obj(build=value, version="8.0"),
        }
        missing = set()
        if interruption in ("vm-disconnected", "host-disconnected"):
            overview["runtime.connectionState"] = "disconnected"
        elif interruption in ("vm-version-missing", "host-missing"):
            missing.add(overview_path)
        elif interruption in ("vm-version-absent", "host-absent"):
            del overview[overview_path]
        elif interruption in ("vm-version-null", "host-null"):
            overview[overview_path] = None
        config = snapshot(t, {})
        refs = reader.normalize_overview([PropertyRow(ref, overview, missing)], config)
        selected = reader.select_vm_details(config.change_versions, baselines or {})
        config.unchanged_vms = refs.keys() - set(selected)
        details = VMDetails()
        if is_vm and ref._moId in selected:
            props = vm_props(value, version)
            path = "config.hardware.device"
            if interruption == "vm-detail-null":
                props[path] = None
            elif interruption == "vm-detail-absent":
                del props[path]
            if interruption == "vm-deferred":
                details.deferred.add("vm")
            elif interruption == "vm-detail-removed":
                details.removed.add("vm")
            else:
                details.rows["vm"] = PropertyRow(
                    ref, props, {path} if interruption == "vm-detail-missing" else set()
                )
        reader.normalize_details(config, selected, details)
        return config, selected

    before, _ = observe(T0, 2 if is_vm else "1", "v1")
    await save(center, before)
    async with session_scope() as session:
        _, baselines = await config_baselines(session, center.id)
    # 切断中の VM に同じ版が返っても近道を使わない。
    interrupted_version = "v1" if mode == "vm-disconnected" else "v2"
    interrupted, selected = observe(
        T1, 4 if is_vm else "2", interrupted_version, mode, baselines
    )
    if mode == "vm-deferred":
        assert interrupted.deferred_vms == {"vm"} and not interrupted.carry_over
    else:
        assert key in interrupted.carry_over
    if mode.startswith("vm-detail") or mode == "vm-deferred":
        assert selected == ["vm"]
    else:
        assert not selected
    await save(center, interrupted)

    rows, diffs, state = await stored(center)
    assert state.config_deferred_count == int(mode == "vm-deferred")
    assert as_utc(rows[key].verified_at) == T0
    assert rows[key].change_version == ("v1" if is_vm else None)
    assert not diffs
    async with session_scope() as session:
        _, baselines = await config_baselines(session, center.id)
    resumed, selected = observe(T2, 4 if is_vm else "2", "v2", baselines=baselines)
    assert selected == (["vm"] if is_vm else [])
    await save(center, resumed)
    rows, (diff,), state = await stored(center)
    assert as_utc(diff.changed_after) == T0
    assert as_utc(diff.observed_at) == T2 + timedelta(seconds=1)
    assert as_utc(rows[key].verified_at) == T2
    assert rows[key].change_version == ("v2" if is_vm else None)
    assert state.config_deferred_count == 0


async def test_empty_array_is_new_value_and_template_disappears():
    center = await add_center()
    switch = "host", "host_vswitch"
    await save(
        center, snapshot(T0, {switch: {"vSwitch0": {"mtu": 1500}}, VM: {"devices": {}}})
    )
    after = snapshot(T1, {})
    reader.normalize_overview(
        [
            PropertyRow(
                vim.HostSystem("host"),
                {
                    "runtime.connectionState": "connected",
                    "config.network.vswitch": [],
                },
                set(),
            ),
            PropertyRow(
                vim.VirtualMachine("vm"), {"summary.config.template": True}, set()
            ),
        ],
        after,
    )
    await save(center, after)
    rows, (diff,), _ = await stored(center)
    assert set(rows) == {switch} and rows[switch].value == {}
    assert (
        diff.element,
        diff.element_label,
        diff.attribute,
        diff.old_value,
        diff.new_value,
    ) == (
        "vSwitch0",
        "vSwitch0",
        None,
        '{"mtu":1500}',
        None,
    )


@pytest.mark.parametrize(
    ("compared", "changed", "warn"),
    [
        (19, 10, False),
        (20, 9, False),
        (20, 10, True),
        (21, 10, False),
        (21, 11, True),
    ],
)
async def test_warning_counts_entities_per_category_and_only_comparable_rows(
    compared, changed, warn
):
    center = await add_center()
    vm_keys = [(f"vm-{i}", "vm_config") for i in range(compared)]
    extra = [
        (f"vm-{name}", "vm_config") for name in ("carry", "deferred", "format", "new")
    ]
    port_keys = [(f"host-{i}", "host_portgroup") for i in range(21)]
    original = {key: {"num_cpu": 2, "devices": {}} for key in vm_keys + extra[:-1]}
    original.update({key: {"pg": {"vlan_id": 1}} for key in port_keys})
    await save(center, snapshot(T0, original))
    async with session_scope() as session:
        await session.execute(
            update(InventoryConfigState)
            .where(InventoryConfigState.moid == "vm-format")
            .values(format=0)
        )

    # 各 VM の複数項目が変わっても、分子は VM の数になる。
    config = snapshot(
        T1,
        {
            **{
                key: {"num_cpu": 4, "memory_mb": 4096, "devices": {}}
                for key in vm_keys[:changed]
            },
            extra[2]: {"num_cpu": 4, "devices": {}},
            extra[3]: {"num_cpu": 4, "devices": {}},
            **{
                key: {"pg": {"vlan_id": 2 if i < 10 else 1}}
                for i, key in enumerate(port_keys)
            },
        },
    )
    config.objects.update(_objects(original))
    config.unchanged_vms = {moid for moid, _ in vm_keys[changed:]}
    config.carry_over.add(extra[0])
    config.deferred_vms.add(extra[1][0])
    await save(center, config)
    _, diffs, status = await stored(center)
    assert len(diffs) == changed * 2 + 10
    if warn:
        assert (
            status.config_last_warning
            == f"vm_config の構成が比較した {compared} 件のうち {changed} 件で変わりました。"
        )
        assert as_utc(status.config_last_warning_at) == config.observed_at
    else:
        assert status.config_last_warning is status.config_last_warning_at is None


async def test_duplicate_names_set_warning_without_minimum_count():
    center = await add_center()
    config = snapshot(T0, {})
    ref = vim.HostSystem("host")
    reader.normalize_overview(
        [
            PropertyRow(
                ref,
                {
                    "runtime.connectionState": "connected",
                    "config.network.vswitch": [
                        Obj(name="s", mtu=1500),
                        Obj(name="s", mtu=9000),
                    ],
                },
                set(),
            )
        ],
        config,
    )
    await save(center, config)
    rows, diffs, status = await stored(center)
    assert rows["host", "host_vswitch"].value["s"]["mtu"] == 1500
    assert not diffs
    assert "host_vswitch" in status.config_last_warning
    assert as_utc(status.config_last_warning_at) == config.observed_at


@pytest.mark.parametrize("retention_days", [30, 2])
@pytest.mark.parametrize("incident_db", ["sqlite", "postgres"], indirect=True)
async def test_config_diff_retention_uses_own_cutoff_observed_at_and_keeps_current(
    monkeypatch, retention_days, incident_db
):
    center = await add_center()
    cutoff = T3 - timedelta(days=retention_days)
    older = cutoff - timedelta(microseconds=1)
    held = ("host-offline", "host_build")
    await save(
        center,
        snapshot(
            older - timedelta(days=1),
            {
                BUILD: {"build": "old"},
                held: {"build": "keep"},
            },
            end=older,
        ),
    )
    for t, build in ((older, "before cutoff"), (cutoff, "at cutoff")):
        config = snapshot(t, {BUILD: {"build": build}}, end=t)
        config.objects[held[0]] = InventoryObjectData("HostSystem", "offline")
        config.carry_over.add(held)
        await save(center, config)
    monkeypatch.setattr(inventory, "utcnow", lambda: T3)
    settings = require_settings().model_copy(
        update={
            "event_retention_days": 7,
            "inventory_config_enabled": False,
            "inventory_config_retention_days": retention_days,
        }
    )
    await purge_retention(settings)
    rows, (diff,), _ = await stored(center)
    assert as_utc(diff.observed_at) == cutoff and as_utc(diff.changed_after) == older
    assert rows[BUILD].value == {"build": "at cutoff"}
    assert rows[held].value == {"build": "keep"}
    assert as_utc(rows[held].verified_at) < cutoff


def test_config_settings_defaults_and_lower_bound():
    assert Settings.model_fields["inventory_sync_timeout_seconds"].default == 300
    assert Settings.model_fields["inventory_config_enabled"].default is True
    assert Settings.model_fields["inventory_config_retention_days"].default == 30
    assert (
        Settings(inventory_config_retention_days=1).inventory_config_retention_days == 1
    )
    with pytest.raises(ValueError, match="greater than or equal to 1"):
        Settings(inventory_config_retention_days=0)


def test_config_mock_uses_same_targets_version_hash_and_exact_thirty_minute_slot():
    def read(t, name="", baselines=None):
        relations = mock_inventory(t, vcenter_name=name)
        config = mock_inventory_config(
            t, observation=relations, vcenter_name=name, baselines=baselines
        )
        assert config.instance_uuid == relations.instance_uuid
        assert config.objects == {
            moid: obj
            for moid, obj in relations.objects.items()
            if obj.entity_type
            in {"HostSystem", "ClusterComputeResource", "VirtualMachine"}
        }
        assert not config.deferred_vms
        return config

    before = read(T0)
    assert len(before.objects) == 6 and len(before.values) == 11
    baselines = {
        moid: ConfigBaseline(version, 1, T0)
        for moid, version in before.change_versions.items()
    }
    assert all(
        version == value_hash(before.values[moid, "vm_config"])
        for moid, version in before.change_versions.items()
    )
    same = read(T0 + timedelta(seconds=1799), baselines=baselines)
    assert same.unchanged_vms == baselines.keys()
    after = read(T0 + timedelta(seconds=1800), baselines=baselines)
    (vm_key,) = (key for key in after.values if key[1] == "vm_config")
    assert (before.values[vm_key]["num_cpu"], after.values[vm_key]["num_cpu"]) == (2, 4)
    demo = read(T0, SCREENSHOT_VCENTER_NAME)
    assert read(T3, SCREENSHOT_VCENTER_NAME).values == demo.values
    assert demo.values[SCREENSHOT_VMS[0][0], "vm_config"]["num_cpu"] == 4
    assert demo.values[SCREENSHOT_VMS[0][0], "vm_config"]["memory_mb"] == 8192
    assert (
        demo.values[SCREENSHOT_HOSTS[0][0], "host_portgroup"]["VM Network"]["vlan_id"]
        == 20
    )


def wire_workers(monkeypatch, config_reader, *, instance="instance"):
    def connect(host, **kwargs):
        return Obj(RetrieveContent=lambda: Obj(host=host))

    observation = InventoryObservation(
        instance,
        {
            "vm": InventoryObjectData("VirtualMachine", "vm"),
            "host": InventoryObjectData("HostSystem", "host"),
        },
        {("vm_host", "vm", "host")},
        set(),
    )
    monkeypatch.setattr(inventory, "connect_vcenter", connect)
    monkeypatch.setattr(inventory, "disconnect", Mock())
    monkeypatch.setattr(inventory, "read_inventory", lambda _: observation)
    monkeypatch.setattr(inventory, "read_inventory_config", config_reader)


async def test_config_exception_leaves_relation_and_sync_records_separate_failure(
    monkeypatch,
):
    center = await add_center()

    def fail(*args, **kwargs):
        raise vmodl.query.InvalidProperty(name="private")

    wire_workers(monkeypatch, fail)
    await inventory.sync_inventory(require_settings())
    rows, diffs, status = await stored(center)
    assert not rows and not diffs
    assert status.last_success_at is not None and status.last_failure_at is None
    assert status.config_last_failure_at is not None
    assert (
        status.config_last_error
        == "vmodl.query.InvalidProperty: collector execution failed"
    )


async def test_relation_is_committed_before_config_timeout_and_has_own_timestamp(
    monkeypatch,
):
    center = await add_center()
    entered, release = Event(), Event()
    times = iter([T0, T1, T3])
    monkeypatch.setattr(inventory, "utcnow", lambda: next(times))
    deadlines = []

    def read(*args, deadline, **kwargs):
        deadlines.append(deadline)
        entered.set()
        release.wait(5)
        return snapshot(T2, {BUILD: {"build": "never stored"}})

    wire_workers(monkeypatch, read)
    settings = require_settings().model_copy(
        update={"inventory_sync_timeout_seconds": 1}
    )
    syncing = asyncio.create_task(inventory.sync_inventory(settings))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        async with asyncio.timeout(0.8):
            while True:
                async with session_scope() as session:
                    edge = await session.scalar(select(InventoryRelation))
                if edge is not None:
                    break
                await asyncio.sleep(0.01)
        assert as_utc(edge.valid_from) == T1
        assert not syncing.done()
        await asyncio.wait_for(syncing, 2)
        rows, diffs, state = await stored(center)
        assert not rows and not diffs
        assert as_utc(state.last_success_at) == T1
        assert (
            state.last_failure_at is None and as_utc(state.config_last_failure_at) == T3
        )
        assert (
            state.config_last_error
            == "ConfigReadTimeout: 構成の読み取りがタイムアウトしました。"
        )
        assert not inventory._reads[center.id].done()
    finally:
        release.set()
        await asyncio.wait_for(syncing, 5)
        await asyncio.wait_for(
            asyncio.gather(
                *(asyncio.wrap_future(future) for future in inventory._reads.values()),
                return_exceptions=True,
            ),
            5,
        )


async def test_worker_deadline_is_exactly_eighty_percent_of_configured_timeout(
    monkeypatch,
):
    await add_center()
    seen = []
    monkeypatch.setattr(inventory, "monotonic", lambda: 7.0)

    def read(*args, deadline, **kwargs):
        seen.append(deadline)
        return snapshot(T0, {BUILD: {"build": "1"}})

    wire_workers(monkeypatch, read)
    settings = require_settings()
    for timeout in (300, 125):
        await inventory.sync_inventory(
            settings.model_copy(update={"inventory_sync_timeout_seconds": timeout})
        )
    assert seen == [247.0, 107.0]


@pytest.mark.parametrize("stop_at", ["config-read", "disconnect"])
async def test_threads_stay_counted_until_disconnect_finishes(monkeypatch, stop_at):
    centers = [await add_center(str(i)) for i in range(3)]
    release = Event()
    reads = []

    def read(content, *args, **kwargs):
        reads.append(content.host)
        if stop_at == "config-read":
            release.wait(5)
        return snapshot(T0, {BUILD: {"build": "1"}})

    def disconnect(_):
        if stop_at == "disconnect":
            release.wait(5)

    wire_workers(monkeypatch, read)
    monkeypatch.setattr(inventory, "disconnect", disconnect)
    settings = require_settings().model_copy(
        update={"inventory_sync_timeout_seconds": 0.2}
    )
    try:
        await inventory.sync_inventory(settings)
        assert len(reads) == len(inventory._reads) == 2
        assert all(future.thread.is_alive() for future in inventory._reads.values())
        assert all(
            future.done() == (stop_at == "disconnect")
            for future in inventory._reads.values()
        )
        for vc in centers[:2]:
            rows, _, state = await stored(vc)
            assert state.last_success_at is not None
            assert bool(rows) == (stop_at == "disconnect")

        await inventory.sync_inventory(settings)
        assert len(reads) == len(inventory._reads) == 2
        for vc in centers[:2]:
            _, _, state = await stored(vc)
            assert state.last_error.startswith("InventoryReadStillRunning:")
            assert state.config_last_error == state.last_error
        _, _, state = await stored(centers[2])
        assert state.last_error.startswith("InventoryWorkerUnavailable:")
    finally:
        release.set()
        for future in inventory._reads.values():
            await asyncio.to_thread(future.thread.join, 5)
            assert not future.thread.is_alive()
            assert future.done()


@pytest.mark.parametrize(
    "failure_at", ["relation-read", "relation-save", "config-save"]
)
async def test_failures_do_not_commit_partial_config_or_relationships(
    monkeypatch, failure_at
):
    center = await add_center()
    wire_workers(
        monkeypatch, lambda *args, **kwargs: snapshot(T0, {BUILD: {"build": "1"}})
    )
    original = {
        "relation-save": inventory.persist_inventory,
        "config-save": inventory.persist_inventory_config,
    }
    names = {
        "relation-read": "read_inventory",
        "relation-save": "persist_inventory",
        "config-save": "persist_inventory_config",
    }

    def fail_read(*_):
        raise RuntimeError("private")

    async def fail_save(*args, **kwargs):
        await original[failure_at](*args, **kwargs)
        await args[0].flush()
        raise RuntimeError("private")

    monkeypatch.setattr(
        inventory,
        names[failure_at],
        fail_read if failure_at == "relation-read" else fail_save,
    )
    await inventory.sync_inventory(require_settings())
    rows, diffs, state = await stored(center)
    assert not rows and not diffs
    assert state.config_last_failure_at is not None
    assert state.config_last_error == "RuntimeError: collector execution failed"
    if failure_at == "config-save":
        assert state.last_success_at is not None and state.last_failure_at is None
    else:
        assert state.last_success_at is None
        assert state.last_failure_at == state.config_last_failure_at
        assert state.last_error == state.config_last_error


async def test_config_instance_is_reset_after_relationship_reset_with_failed_config(
    monkeypatch,
):
    center = await add_center()
    configurations = [
        snapshot(T0, {VM: {"num_cpu": 2, "devices": {}}}, instance="old"),
        snapshot(T2, {VM: {"num_cpu": 4, "devices": {}}}, instance="new"),
    ]
    configurations[0].change_versions["vm"] = configurations[1].change_versions[
        "vm"
    ] = "same"
    first = Mock(return_value=configurations[0])
    wire_workers(monkeypatch, first, instance="old")
    await inventory.sync_inventory(require_settings())

    fail = Mock(side_effect=RuntimeError("config failed"))
    wire_workers(monkeypatch, fail, instance="new")
    await inventory.sync_inventory(require_settings())
    rows, _, state = await stored(center)
    assert state.instance_uuid == "new" and state.config_instance_uuid == "old"
    assert rows[VM].value["num_cpu"] == 2

    next_read = Mock(return_value=configurations[1])
    wire_workers(monkeypatch, next_read, instance="new")
    await inventory.sync_inventory(require_settings())
    assert next_read.call_args.args[2] == {}
    rows, diffs, state = await stored(center)
    assert not diffs and rows[VM].value["num_cpu"] == 4
    assert state.config_instance_uuid == "new"
    assert as_utc(state.config_first_success_at) == as_utc(state.config_last_success_at)
    assert as_utc(state.config_first_success_at) == configurations[1].observed_at

    await inventory.sync_inventory(require_settings())
    baselines = next_read.call_args.args[2]
    assert baselines.keys() == {"vm"}
    assert (baselines["vm"].change_version, baselines["vm"].format) == ("same", 1)
    assert as_utc(baselines["vm"].verified_at) == T2


async def test_disabling_config_preserves_current_and_disabling_inventory_skips_both(
    monkeypatch,
):
    center = await add_center()
    await save(center, snapshot(T0, {BUILD: {"build": "1"}}))
    read = Mock(return_value=snapshot(T2, {BUILD: {"build": "2"}}))
    wire_workers(monkeypatch, read)
    settings = require_settings()
    await inventory.sync_inventory(
        settings.model_copy(update={"inventory_config_enabled": False})
    )
    read.assert_not_called()
    rows, diffs, state = await stored(center)
    assert not diffs and as_utc(rows[BUILD].verified_at) == T0
    assert state.last_success_at is not None

    await inventory.sync_inventory(
        settings.model_copy(update={"inventory_sync_enabled": False})
    )
    read.assert_not_called()
    _, _, unchanged = await stored(center)
    assert unchanged.last_success_at == state.last_success_at

    await inventory.sync_inventory(settings)
    _, (diff,), _ = await stored(center)
    assert as_utc(diff.changed_after) == T0


async def test_config_mock_goes_through_sync_and_diffs_at_slot_boundary(monkeypatch):
    center = await add_center()
    settings = require_settings().model_copy(update={"mock_mode": True})
    connect = Mock(side_effect=AssertionError("モックは接続しない"))
    monkeypatch.setattr(inventory, "connect_vcenter", connect)
    monkeypatch.setattr(inventory, "utcnow", lambda: T0)
    await inventory.sync_inventory(settings)
    rows, diffs, sync = await stored(center)
    assert len(rows) == 11 and not diffs
    assert sync.config_object_count == 6 and sync.config_deferred_count == 0
    monkeypatch.setattr(inventory, "utcnow", lambda: T0 + timedelta(minutes=30))
    await inventory.sync_inventory(settings)
    _, (diff,), _ = await stored(center)
    assert (diff.attribute, diff.old_value, diff.new_value) == ("num_cpu", "2", "4")
    connect.assert_not_called()


async def test_config_future_wait_uses_only_remaining_time_after_relationship_save(
    monkeypatch,
):
    center = await add_center()
    release = Event()
    ticks = [10.0]
    calls = []
    real_timeout = asyncio.timeout
    persist = inventory.persist_inventory

    def monotonic():
        return ticks[0]

    async def save_relations(*args, **kwargs):
        await persist(*args, **kwargs)
        ticks[0] = 69.75

    def track_timeout(seconds):
        calls.append(seconds)
        if len(calls) == 2:
            release.set()
        return real_timeout(seconds)

    def read(*args, **kwargs):
        assert release.wait(5)
        return snapshot(T0, {BUILD: {"build": "1"}})

    wire_workers(monkeypatch, read)
    monkeypatch.setattr(inventory, "monotonic", monotonic)
    monkeypatch.setattr(inventory, "persist_inventory", save_relations)
    monkeypatch.setattr(asyncio, "timeout", track_timeout)
    await asyncio.wait_for(
        inventory.sync_inventory(
            require_settings().model_copy(
                update={"inventory_sync_timeout_seconds": 300}
            )
        ),
        5,
    )
    assert calls == [300, 240.25]
    rows, _, state = await stored(center)
    assert BUILD in rows and state.config_last_failure_at is None


async def test_carry_over_and_deferred_precede_the_vm_shortcut():
    center = await add_center()
    original = snapshot(T0, {VM: {"num_cpu": 2, "devices": {}}})
    original.change_versions["vm"] = "v1"
    await save(center, original)
    for unread, deferred in ((True, False), (False, True)):
        config = snapshot(T1, {VM: {"num_cpu": 4, "devices": {}}})
        config.values.clear()
        config.change_versions["vm"] = "v1"
        config.unchanged_vms = {"vm"}
        if unread:
            config.carry_over.add(VM)
        if deferred:
            config.deferred_vms.add("vm")
        await save(center, config)
        rows, diffs, _ = await stored(center)
        assert as_utc(rows[VM].verified_at) == T0
        assert not diffs


async def test_same_vm_generation_advances_verified_at_before_later_diff():
    center = await add_center()
    original = snapshot(T0, {VM: {"num_cpu": 2, "devices": {}}})
    original.change_versions["vm"] = "v1"
    await save(center, original)

    same = snapshot(T1, {})
    same.objects["vm"] = InventoryObjectData("VirtualMachine", "renamed")
    same.change_versions["vm"] = "v1"
    same.unchanged_vms.add("vm")
    await save(center, same)
    rows, diffs, _ = await stored(center)
    assert not diffs
    assert as_utc(rows[VM].verified_at) == T1
    assert rows[VM].entity_name == "renamed"

    generation_only = snapshot(T2, {VM: {"num_cpu": 2, "devices": {}}})
    generation_only.change_versions["vm"] = "v2"
    await save(center, generation_only)
    rows, diffs, _ = await stored(center)
    assert not diffs
    assert rows[VM].change_version == "v2"
    assert as_utc(rows[VM].verified_at) == T2

    changed = snapshot(T3, {VM: {"num_cpu": 4, "devices": {}}})
    changed.change_versions["vm"] = "v3"
    await save(center, changed)
    _, (diff,), _ = await stored(center)
    assert as_utc(diff.changed_after) == T2
    assert (diff.old_value, diff.new_value) == ("2", "4")


async def test_config_none_is_recorded_after_relationship_success(monkeypatch):
    center = await add_center()
    wire_workers(monkeypatch, Mock(return_value=None))
    await inventory.sync_inventory(require_settings())
    _, _, state = await stored(center)
    assert state.last_success_at is not None and state.last_failure_at is None
    assert state.config_last_success_at is None
    assert state.config_last_failure_at is not None
    assert (
        state.config_last_error
        == "ConfigReadMissing: 構成の読み取り結果を受け取れませんでした。"
    )


async def test_config_baseline_failure_records_original_failure_and_still_saves_relationships(
    monkeypatch,
):
    center = await add_center()
    await save(center, snapshot(T0, {BUILD: {"build": "existing"}}))
    read = Mock(return_value=snapshot(T1, {BUILD: {"build": "changed"}}))
    wire_workers(monkeypatch, read)
    baseline_failure = AsyncMock(side_effect=LookupError("private"))
    monkeypatch.setattr(inventory, "config_baselines", baseline_failure)
    await inventory.sync_inventory(require_settings())
    baseline_failure.assert_awaited_once()
    read.assert_not_called()
    rows, diffs, state = await stored(center)
    assert rows[BUILD].value == {"build": "existing"} and not diffs
    assert state.last_success_at is not None and state.last_failure_at is None
    assert as_utc(state.config_last_success_at) == T0 + timedelta(seconds=1)
    assert state.config_last_failure_at is not None
    assert state.config_last_error == "LookupError: collector execution failed"


@pytest.mark.parametrize("config_enabled", [False, True])
async def test_relationship_failure_finishes_config_future_and_only_writes_config_status_if_enabled(
    monkeypatch,
    config_enabled,
):
    center = await add_center()
    read_config = Mock()
    wire_workers(monkeypatch, read_config)
    monkeypatch.setattr(
        inventory, "read_inventory", Mock(side_effect=RuntimeError("private"))
    )
    settings = require_settings().model_copy(
        update={"inventory_config_enabled": config_enabled}
    )
    await inventory.sync_inventory(settings)
    read_config.assert_not_called()
    pending = inventory._reads[center.id]
    assert await asyncio.wait_for(asyncio.wrap_future(pending), 5) is None
    _, _, state = await stored(center)
    assert (
        state.last_failure_at is not None
        and state.last_error == "RuntimeError: collector execution failed"
    )
    if config_enabled:
        assert state.config_last_failure_at == state.last_failure_at
        assert state.config_last_error == state.last_error
    else:
        assert state.config_last_failure_at is None
        assert state.config_last_error is None
        assert state.config_last_started_at is None


async def test_config_disabled_finishes_future_after_disconnect(monkeypatch):
    center = await add_center()
    release = Event()
    read = Mock()
    wire_workers(monkeypatch, read)
    monkeypatch.setattr(inventory, "disconnect", lambda _: release.wait(5))
    settings = require_settings().model_copy(update={"inventory_config_enabled": False})
    try:
        await asyncio.wait_for(inventory.sync_inventory(settings), 5)
        future = inventory._reads[center.id]
        assert future.thread.is_alive() and not future.done()
        read.assert_not_called()
    finally:
        release.set()
        for pending in inventory._reads.values():
            assert await asyncio.wait_for(asyncio.wrap_future(pending), 5) is None


async def test_completed_config_result_does_not_start_new_timeout(monkeypatch):
    future = Future()
    result = snapshot(T0, {})
    future.set_result(result)
    timeout = Mock(wraps=asyncio.timeout)
    monkeypatch.setattr(asyncio, "timeout", timeout)
    monkeypatch.setattr(inventory, "monotonic", lambda: 500.0)
    assert await inventory._wait_for_config(future, 300.0) is result
    timeout.assert_not_called()


async def test_config_result_completed_after_worker_expiry_is_rejected_even_if_already_done(
    monkeypatch,
):
    center = await add_center()
    release = Event()
    fake_time = [10.0]
    monkeypatch.setattr(inventory, "monotonic", lambda: fake_time[0])

    def read(*args, **kwargs):
        assert release.wait(5)
        fake_time[0] = 310.0
        return snapshot(T0, {BUILD: {"build": "late"}})

    wire_workers(monkeypatch, read)
    save_relationships = inventory.persist_inventory

    async def persist(*args, **kwargs):
        release.set()
        future = inventory._reads[center.id]
        await asyncio.to_thread(future.thread.join, 5)
        assert future.done()
        await save_relationships(*args, **kwargs)

    monkeypatch.setattr(inventory, "persist_inventory", persist)
    await inventory.sync_inventory(
        require_settings().model_copy(update={"inventory_sync_timeout_seconds": 300})
    )
    rows, diffs, state = await stored(center)
    assert not rows and not diffs
    assert state.last_success_at is not None and state.last_failure_at is None
    assert (
        state.config_last_error
        == "ConfigReadTimeout: 構成の読み取りがタイムアウトしました。"
    )


@pytest.mark.parametrize("already_done", [False, True])
async def test_config_socket_timeout_is_recorded_as_collector_error(
    monkeypatch, already_done
):
    center = await add_center()
    release = Event()
    real_timeout = asyncio.timeout
    seconds = []

    def read(*args, **kwargs):
        assert release.wait(5)
        raise TimeoutError("private")

    def timeout(delay):
        seconds.append(delay)
        if len(seconds) == 2:
            release.set()
        return real_timeout(delay)

    original = inventory.persist_inventory

    async def persist(*args, **kwargs):
        if already_done:
            release.set()
            future = inventory._reads[center.id]
            await asyncio.to_thread(future.thread.join, 5)
            assert future.done()
        await original(*args, **kwargs)

    wire_workers(monkeypatch, read)
    monkeypatch.setattr(asyncio, "timeout", timeout)
    monkeypatch.setattr(inventory, "persist_inventory", persist)
    try:
        await asyncio.wait_for(inventory.sync_inventory(require_settings()), 5)
        _, _, state = await stored(center)
        assert len(seconds) == (1 if already_done else 2)
        assert state.last_success_at is not None and state.last_error is None
        assert state.config_last_failure_at is not None
        assert state.config_last_error == "TimeoutError: collector execution failed"
    finally:
        release.set()


@pytest.mark.parametrize(("version", "format_"), [("old", 1), ("v1", 0)])
async def test_stale_vm_shortcut_checks_both_format_and_generation(version, format_):
    center = await add_center()
    original = snapshot(T0, {VM: {"num_cpu": 2, "devices": {}}})
    original.change_versions["vm"] = "v1"
    await save(center, original)
    async with session_scope() as session:
        await session.execute(update(InventoryConfigState).values(format=format_))
    shortcut = snapshot(T1, {})
    shortcut.objects["vm"] = InventoryObjectData("VirtualMachine", "different")
    shortcut.change_versions["vm"] = version
    shortcut.unchanged_vms.add("vm")
    await save(center, shortcut)
    rows, diffs, _ = await stored(center)
    assert not diffs
    assert as_utc(rows[VM].verified_at) == T0
    assert rows[VM].entity_name == "vm"


@pytest.mark.parametrize("incident_db", ["sqlite", "postgres"], indirect=True)
async def test_config_diff_baselines_read_timezone_aware_verified_at(incident_db):
    center = await add_center()
    time = T0.astimezone(timezone(timedelta(hours=9)))
    observed = snapshot(time, {VM: {"num_cpu": 2, "devices": {}}})
    observed.change_versions["vm"] = "v1"
    await save(center, observed)
    async with session_scope() as session:
        instance, baselines = await config_baselines(session, center.id)
    assert instance == observed.instance_uuid
    assert baselines == {"vm": ConfigBaseline("v1", 1, T0)}
    assert baselines["vm"].verified_at.utcoffset() == timedelta(0)


async def test_stage_two_optional_fields_are_compared_and_unread_count_is_separate():
    center = await add_center()
    ref = vim.VirtualMachine("vm")
    unread = vim.VirtualMachine("unread")
    deferred = vim.VirtualMachine("deferred")
    deferred2 = vim.VirtualMachine("deferred2")

    def details(t, *, optional):
        config = snapshot(t, {})
        props = vm_props(2, "v1" if optional else "v2")
        props.update(
            {
                "config.cpuAllocation": Obj(
                    reservation=100, limit=-1, shares=Obj(level="high")
                ),
                "config.memoryAllocation": Obj(
                    reservation=1024, limit=-1, shares=Obj(level="low")
                ),
            }
        )
        vm_details = {}
        if not optional:
            del props["config.hardware.numCoresPerSocket"]
            del props["config.guestId"]
            del props["config.version"]
            del props["config.cpuAllocation"]
            props["config.memoryAllocation"] = None
            vm_details["unread"] = PropertyRow(
                unread, {"config.changeVersion": "v2"}, set()
            )
        vm_details["vm"] = PropertyRow(ref, props, set())
        config.objects = {
            r._moId: InventoryObjectData("VirtualMachine", "vm")
            for r in (ref, unread, deferred, deferred2)
        }
        reader.normalize_details(
            config,
            ["vm", "unread", "deferred", "deferred2"] if not optional else ["vm"],
            VMDetails(
                rows=vm_details,
                deferred={"deferred", "deferred2"} if not optional else set(),
            ),
        )
        return config

    before = details(T0, optional=True)
    before.values["unread", "vm_config"] = {"num_cpu": 2, "devices": {}}
    before.change_versions["unread"] = "v1"
    await save(center, before)
    after = details(T1, optional=False)
    assert after.unread_vms == {"unread"}
    assert after.deferred_vms == {"deferred", "deferred2"}
    await save(center, after)
    rows, diffs, state = await stored(center)
    keys = {
        "cores_per_socket",
        "hardware_version",
        "guest_id",
        "cpu_reservation_mhz",
        "cpu_limit_mhz",
        "cpu_shares",
        "memory_reservation_mb",
        "memory_limit_mb",
        "memory_shares",
    }
    assert {diff.attribute for diff in diffs} == keys
    assert all(diff.new_value == "null" for diff in diffs)
    assert all(rows[VM].value[key] is None for key in keys)
    assert as_utc(rows[VM].verified_at) == T1
    assert as_utc(rows["unread", "vm_config"].verified_at) == T0
    assert rows["unread", "vm_config"].change_version == "v1"
    assert state.config_deferred_count == 2
    assert (
        state.config_last_warning == "段 2 で構成を読めなかった VM が 1 台ありました。"
    )
    assert as_utc(state.config_last_warning_at) == after.observed_at


@pytest.mark.parametrize(
    "path",
    [
        "config.hardware.numCoresPerSocket",
        "config.version",
        "config.guestId",
        "config.cpuAllocation",
        "config.memoryAllocation",
    ],
)
@pytest.mark.parametrize("returned_in_prop_set", [False, True])
async def test_stage_two_optional_missing_set_carries_value_until_readable(
    path, returned_in_prop_set
):
    center = await add_center()
    ref = vim.VirtualMachine("vm")

    def observe(t, version, *, failed=False):
        config = snapshot(t, {})
        config.objects["vm"] = InventoryObjectData("VirtualMachine", "vm")
        props = vm_props(2, version)
        props["config.cpuAllocation"] = Obj(
            reservation=100, limit=-1, shares=Obj(level="high")
        )
        props["config.memoryAllocation"] = Obj(
            reservation=1024, limit=-1, shares=Obj(level="low")
        )
        if failed and not returned_in_prop_set:
            del props[path]
        reader.normalize_details(
            config,
            ["vm"],
            VMDetails({"vm": PropertyRow(ref, props, {path} if failed else set())}),
        )
        return config

    before = observe(T0, "v1")
    await save(center, before)
    interrupted = observe(T1, "v2", failed=True)
    assert interrupted.unread_vms == {"vm"}
    assert interrupted.carry_over == {VM}
    await save(center, interrupted)
    rows, diffs, state = await stored(center)
    assert not diffs and rows[VM].value == before.values[VM]
    assert rows[VM].change_version == "v1"
    assert as_utc(rows[VM].verified_at) == T0
    assert (
        state.config_last_warning == "段 2 で構成を読めなかった VM が 1 台ありました。"
    )
    assert state.config_deferred_count == 0

    await save(center, observe(T2, "v2"))
    rows, diffs, _ = await stored(center)
    assert not diffs and rows[VM].change_version == "v2"
    assert as_utc(rows[VM].verified_at) == T2


@pytest.mark.parametrize("with_unread", [False, True])
async def test_removed_vm_keeps_baseline_without_contributing_to_warning(with_unread):
    center = await add_center()
    other = ("unread", "vm_config")
    initial = {VM: {"num_cpu": 2, "devices": {}}}
    if with_unread:
        initial[other] = {"num_cpu": 2, "devices": {}}
    before = snapshot(T0, initial)
    before.change_versions["vm"] = "v1"
    await save(center, before)

    config = snapshot(T1, {})
    config.objects.update(before.objects)
    reader.normalize_details(config, config.objects, VMDetails(removed={"vm"}))
    assert config.removed_vms == {"vm"}
    assert config.unread_vms == set(config.objects)
    assert (VM in config.carry_over) and not config.deferred_vms
    await save(center, config)

    rows, diffs, state = await stored(center)
    assert not diffs and rows[VM].value == before.values[VM]
    assert rows[VM].change_version == "v1" and as_utc(rows[VM].verified_at) == T0
    assert state.config_deferred_count == 0
    assert state.config_last_warning == (
        "段 2 で構成を読めなかった VM が 1 台ありました。" if with_unread else None
    )


async def test_unreadable_disk_preserves_vm_config_and_warns():
    center = await add_center()
    ref = vim.VirtualMachine("vm")
    root = vim.vm.device.VirtualDisk.FlatVer2BackingInfo(
        thinProvisioned=True, diskMode="persistent"
    )
    disk = vim.vm.device.VirtualDisk(key=2000, backing=root)

    def observe(t, version):
        config = snapshot(t, {})
        config.objects["vm"] = InventoryObjectData("VirtualMachine", "vm")
        props = vm_props(2, version)
        props["config.hardware.device"] = [disk]
        reader.normalize_details(
            config,
            ["vm"],
            VMDetails({"vm": PropertyRow(ref, props, set())}),
        )
        return config

    before = observe(T0, "v1")
    await save(center, before)
    disk.backing = None
    await save(center, observe(T1, "v2"))
    rows, diffs, state = await stored(center)
    assert not diffs and rows[VM].value == before.values[VM]
    assert rows[VM].change_version == "v1" and as_utc(rows[VM].verified_at) == T0
    assert (
        state.config_last_warning == "段 2 で構成を読めなかった VM が 1 台ありました。"
    )

    disk.backing = root
    await save(center, observe(T2, "v2"))
    rows, diffs, _ = await stored(center)
    assert not diffs and rows[VM].change_version == "v2"
    assert as_utc(rows[VM].verified_at) == T2


async def test_config_diff_reads_json_only_for_rows_with_changes_in_same_format():
    center = await add_center()
    same = ("same", "host_build")
    different_format = ("format", "host_build")
    await save(
        center,
        snapshot(
            T0, {key: {"build": "old"} for key in (BUILD, same, different_format)}
        ),
    )
    async with session_scope() as session:
        await session.execute(
            update(InventoryConfigState)
            .where(
                InventoryConfigState.moid == different_format[0],
            )
            .values(format=0)
        )
    rows, _, _ = await stored(center)

    calls = []

    def on_sql(conn, cursor, statement, parameters, context, executemany):
        if (
            statement.startswith("SELECT")
            and "FROM inventory_config_states" in statement
        ):
            columns = statement.split("FROM", 1)[0]
            if (
                "inventory_config_states.value " in columns.rstrip() + " "
                or "inventory_config_states.value," in columns
            ):
                calls.append(parameters)

    async with session_scope() as session:
        bind = session.get_bind()
        event.listen(bind, "before_cursor_execute", on_sql)
        try:
            await persist_inventory_config(
                session,
                center.id,
                snapshot(
                    T1,
                    {
                        BUILD: {"build": "changed"},
                        same: {"build": "old"},
                        different_format: {"build": "new format"},
                    },
                ),
            )
        finally:
            event.remove(bind, "before_cursor_execute", on_sql)

    assert calls == [(rows[BUILD].id,)]
    _, (diff,), _ = await stored(center)
    assert diff.moid == BUILD[0] and (diff.old_value, diff.new_value) == (
        '"old"',
        '"changed"',
    )
