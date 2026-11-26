"""構成の正規化と PropertyCollector の読み取りの試験。"""

from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
from types import SimpleNamespace as Obj
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pyVmomi import SoapAdapter, vim, vmodl

from vcenter_event_assistant.collectors import inventory_config as reader
from vcenter_event_assistant.collectors.config_values import (
    VM_DETAIL_PATHS,
    diff_config,
    normalize_ha,
    normalize_host_network,
    normalize_vm,
    value_hash,
)
from vcenter_event_assistant.collectors.inventory_config import (
    ConfigBaseline,
    ConfigObservation,
    PropertyRow,
)

NOW = datetime(2026, 11, 26, tzinfo=timezone.utc)
INF = float("inf")


class VirtualDisk(Obj):
    pass


class VirtualEthernetCard(Obj):
    pass


class VirtualVmxnet3(VirtualEthernetCard):
    pass


class NetworkBackingInfo(Obj):
    pass


class DistributedVirtualPortBackingInfo(Obj):
    pass


class OpaqueNetworkBackingInfo(Obj):
    pass


class FailoverLevelAdmissionControlPolicy(Obj):
    pass


class FailoverHostAdmissionControlPolicy(Obj):
    pass


class FailoverResourcesAdmissionControlPolicy(Obj):
    pass


def vm_details(*devices, version="v1", cpu=2):
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
                Obj(reservation=1, limit=-1, shares=Obj(level="custom", shares=100)),
                Obj(reservation=2, limit=-1, shares=Obj(level="normal", shares=200)),
                list(devices),
            ),
            strict=True,
        )
    )


def network_entry(switches=True):
    teaming = Obj(
        policy="loadbalance_srcid",
        nicOrder=Obj(
            activeNic=["vmnic0", "vmnic1"],
            standbyNic=["vmnic2", "vmnic3"],
        ),
    )
    policy = Obj(
        nicTeaming=teaming, security=Obj(allowPromiscuous=False, macChanges=True)
    )
    spec = Obj(name="pg", vlanId=10, vswitchName="vSwitch0", policy=policy)
    if switches:
        return Obj(
            name="vSwitch0",
            mtu=1500,
            pnic=[
                "key-vim.host.PhysicalNic-vmnic1",
                "key-vim.host.PhysicalNic-vmnic0",
            ],
            spec=spec,
            numPorts=32,
            numPortsAvailable=31,
        )
    return Obj(
        spec=spec,
        port=["port-1"],
        computedPolicy=Obj(security=Obj(forgedTransmits=True)),
    )


@pytest.mark.parametrize(
    ("switches", "excluded", "replacement"),
    [
        (True, "numPorts", 100),
        (True, "numPortsAvailable", 200),
        (False, "port", ["port-2"]),
    ],
)
def test_network_ignores_dynamic_fields(switches, excluded, replacement):
    entry = network_entry(switches)
    category = "host_vswitch" if switches else "host_portgroup"
    before, _ = normalize_host_network([entry], switches=switches)
    setattr(entry, excluded, replacement)
    after, _ = normalize_host_network([entry], switches=switches)
    assert value_hash(before) == value_hash(after)
    assert not list(diff_config(category, before, after))


def test_network_order_duplicates_and_individual_overrides():
    entry = network_entry()
    before, duplicate = normalize_host_network([entry], switches=True)
    assert not duplicate
    assert before["vSwitch0"] == {
        "mtu": 1500,
        "uplinks": ["vmnic0", "vmnic1"],
        "teaming_policy": "loadbalance_srcid",
        "active_nics": ["vmnic0", "vmnic1"],
        "standby_nics": ["vmnic2", "vmnic3"],
        "allow_promiscuous": False,
        "mac_changes": True,
        "forged_transmits": None,
    }
    entry.pnic.reverse()
    switched, _ = normalize_host_network([entry], switches=True)
    assert not list(diff_config("host_vswitch", before, switched))
    order = entry.spec.policy.nicTeaming.nicOrder
    order.activeNic.reverse()
    order.standbyNic.reverse()
    switched, _ = normalize_host_network([entry], switches=True)
    diffs = list(diff_config("host_vswitch", before, switched))
    assert [(d.attribute, d.element_label) for d in diffs] == [
        ("active_nics", "vSwitch0"),
        ("standby_nics", "vSwitch0"),
    ]
    pg = network_entry(False)
    pg.spec.policy.nicTeaming.nicOrder = Obj(activeNic=["vmnic0"])
    duplicates, duplicate = normalize_host_network(
        [
            pg,
            Obj(spec=Obj(name="pg", vlanId=99)),
        ],
        switches=False,
    )
    assert duplicate and duplicates == {
        "pg": {
            "vlan_id": 10,
            "vswitch": "vSwitch0",
            "teaming_policy": "loadbalance_srcid",
            "active_nics": ["vmnic0"],
            "standby_nics": None,
            "allow_promiscuous": False,
            "mac_changes": True,
            "forged_transmits": None,
        }
    }


def test_ha_policy_types_and_automatic_percentages():
    class Monitoring(Enum):
        enabled = "enabled"

    settings = Obj(
        hostMonitoring=Monitoring.enabled,
        failoverLevel=99,
        defaultVmSettings=Obj(restartPriority="high", isolationResponse="none"),
    )
    assert normalize_ha(settings)["host_monitoring"] == "enabled"
    assert normalize_ha(settings)["failover_level"] is None
    settings.admissionControlPolicy = FailoverLevelAdmissionControlPolicy(
        failoverLevel=2
    )
    level = normalize_ha(settings)
    assert (level["admission_control_policy"], level["failover_level"]) == ("Level", 2)
    assert (level["restart_priority"], level["isolation_response"]) == ("high", "none")
    settings.admissionControlPolicy = FailoverResourcesAdmissionControlPolicy(
        autoComputePercentages=True,
        cpuFailoverResourcesPercent=20,
        memoryFailoverResourcesPercent=10,
    )
    automatic = normalize_ha(settings)
    settings.admissionControlPolicy.cpuFailoverResourcesPercent = 35
    settings.admissionControlPolicy.memoryFailoverResourcesPercent = 40
    assert not list(diff_config("cluster_ha", automatic, normalize_ha(settings)))
    settings.admissionControlPolicy.autoComputePercentages = False
    manual = normalize_ha(settings)
    assert (
        manual["auto_compute"],
        manual["cpu_failover_percent"],
        manual["memory_failover_percent"],
    ) == (False, 35, 40)
    settings.admissionControlPolicy = FailoverHostAdmissionControlPolicy(
        failoverHosts=[Obj(_moId="host-b"), Obj(_moId="host-a")],
    )
    hosts = normalize_ha(settings)
    assert hosts["failover_hosts"] == ["host-a", "host-b"]
    settings.admissionControlPolicy.failoverHosts.reverse()
    assert hosts == normalize_ha(settings)
    assert all(
        hosts[key] is None
        for key in ("auto_compute", "cpu_failover_percent", "memory_failover_percent")
    )


@pytest.mark.parametrize(
    ("backing", "network"),
    [
        (NetworkBackingInfo(deviceName="VM Network"), "VM Network"),
        (
            DistributedVirtualPortBackingInfo(
                port=Obj(portgroupKey="dvpg", portKey="ignored")
            ),
            "dvpg",
        ),
        (OpaqueNetworkBackingInfo(opaqueNetworkId="nsx"), "nsx"),
        (Obj(deviceName="無関係"), None),
    ],
)
def test_vm_devices_use_keys_and_ignore_runtime(backing, network):
    disk = VirtualDisk(
        key=2000,
        deviceInfo=Obj(label="Disk"),
        capacityInKB=1024,
        backing=Obj(thinProvisioned=True, diskMode="persistent", fileName="base"),
    )
    nic = VirtualVmxnet3(
        key=4012,
        deviceInfo=Obj(label="NIC"),
        backing=backing,
        macAddress="11:22",
        connectable=Obj(startConnected=True, connected=False),
    )
    before = normalize_vm(vm_details(disk, nic, Obj(key=4013)))
    assert before == {
        "num_cpu": 2,
        "cores_per_socket": 1,
        "memory_mb": 4096,
        "hardware_version": "vmx-21",
        "guest_id": "otherGuest64",
        "cpu_reservation_mhz": 1,
        "cpu_limit_mhz": -1,
        "cpu_shares": "custom:100",
        "memory_reservation_mb": 2,
        "memory_limit_mb": -1,
        "memory_shares": "normal",
        "devices": {
            "disk:2000": {
                "label": "Disk",
                "uuid": None,
                "capacity_kb": 1024,
                "thin": True,
                "disk_mode": "persistent",
            },
            "nic:4012": {
                "label": "NIC",
                "adapter": "VirtualVmxnet3",
                "network": network,
                "start_connected": True,
                "mac_address": "11:22",
            },
        },
    }
    disk.backing.fileName = "delta"
    assert not list(
        diff_config("vm_config", before, normalize_vm(vm_details(disk, nic)))
    )
    nic.connectable.connected = True
    assert not list(
        diff_config("vm_config", before, normalize_vm(vm_details(disk, nic)))
    )
    assert not list(
        diff_config("vm_config", before, normalize_vm(vm_details(nic, disk)))
    )
    nic.deviceInfo.label = "新しいラベル"
    after = normalize_vm(vm_details(nic, disk))
    (diff,) = diff_config("vm_config", before, after)
    assert (
        diff.element,
        diff.attribute,
        diff.element_label,
        diff.old_value,
        diff.new_value,
    ) == (
        "nic:4012",
        "label",
        "新しいラベル",
        '"NIC"',
        '"新しいラベル"',
    )
    (added,) = diff_config("vm_config", normalize_vm(vm_details(disk)), after)
    (deleted,) = diff_config("vm_config", after, normalize_vm(vm_details(disk)))
    assert added.element == deleted.element == "nic:4012"
    assert added.attribute is deleted.attribute is None
    assert added.old_value is deleted.new_value is None
    assert added.new_value == deleted.old_value
    assert added.element_label == deleted.element_label == "新しいラベル"


def test_diff_distinguishes_null_and_clips_json_at_exact_character_limit():
    original = {"pg": {"active_nics": None}}
    boundary = "日" * 1022
    (diff,) = diff_config("host_portgroup", original, {"pg": {"active_nics": boundary}})
    assert (
        diff.old_value == "null"
        and diff.new_value == f'"{boundary}"'
        and not diff.truncated
    )
    (diff,) = diff_config(
        "host_portgroup", {"pg": {"active_nics": boundary + "日"}}, original
    )
    assert len(diff.old_value) == 1024 and diff.old_value == '"' + "日" * 1023
    assert diff.new_value == "null" and diff.truncated


def raw(ref, props, missing=()):
    return Obj(
        obj=ref,
        propSet=[Obj(name=name, val=val) for name, val in props.items()],
        missingSet=[Obj(path=path) for path in missing],
    )


def pc_content(*initial_pages):
    collector = Mock()
    collector.RetrievePropertiesEx.side_effect = list(initial_pages)
    view = vim.view.ContainerView("view-1")
    view_manager = Mock()
    view_manager.CreateContainerView.return_value = view
    content = Obj(
        rootFolder=vim.Folder("folder-1"),
        propertyCollector=collector,
        viewManager=view_manager,
        about=Obj(instanceUuid="instance"),
    )
    return content, collector


def page(*rows, token=None):
    return Obj(token=token, objects=rows)


def vm_overview(ref, version="v1", **props):
    return raw(
        ref,
        {
            "name": "vm",
            "runtime.connectionState": "connected",
            "summary.config.template": False,
            "config.changeVersion": version,
            **props,
        },
    )


def test_overview_fallback_is_per_vcenter_and_cached_only_on_success(monkeypatch):
    monkeypatch.setattr(reader, "_FALLBACK_CLUSTER_PATHS", set())
    host = vim.HostSystem("host-1")
    cluster = vim.ClusterComputeResource("cluster-1")
    result = page(
        raw(
            host,
            {
                "runtime.connectionState": "connected",
                "summary.config.product": Obj(version="8.0", build="10"),
            },
        ),
        raw(
            cluster,
            {
                "configurationEx.dasConfig": Obj(enabled=False),
                "configurationEx.drsConfig": Obj(
                    enabled=True, defaultVmBehavior="manual", vmotionRate=3
                ),
            },
        ),
    )
    content, collector = pc_content(
        vmodl.query.InvalidProperty(), result, result, page()
    )
    cid = uuid4()
    first = reader.read_inventory_config(content, cid, {}, deadline=INF)
    assert first.cluster_path == "configurationEx"
    assert first.values["host-1", "host_build"] == {"version": "8.0", "build": "10"}
    assert first.values["cluster-1", "cluster_drs"] == {
        "enabled": True,
        "default_vm_behavior": "manual",
        "vmotion_rate": 3,
    }
    second = reader.read_inventory_config(content, cid, {}, deadline=INF)
    assert second.cluster_path == "configurationEx"
    third = reader.read_inventory_config(content, uuid4(), {}, deadline=INF)
    assert third.cluster_path == "configuration"
    calls = collector.RetrievePropertiesEx.call_args_list
    paths = [
        {p.type._wsdlName: list(p.pathSet) for p in call.kwargs["specSet"][0].propSet}
        for call in calls
    ]
    assert paths[0] == {
        "HostSystem": [
            "name",
            "runtime.connectionState",
            "summary.config.product",
            "config.network.vswitch",
            "config.network.portgroup",
        ],
        "ClusterComputeResource": [
            "name",
            "configuration.dasConfig",
            "configuration.drsConfig",
        ],
        "VirtualMachine": [
            "name",
            "runtime.connectionState",
            "summary.config.template",
            "config.changeVersion",
        ],
    }
    assert [p["ClusterComputeResource"][1] for p in paths] == [
        "configuration.dasConfig",
        "configurationEx.dasConfig",
        "configurationEx.dasConfig",
        "configuration.dasConfig",
    ]

    content, collector = pc_content(
        vmodl.query.InvalidProperty(), vmodl.query.InvalidProperty(), page()
    )
    cid = uuid4()
    with pytest.raises(vmodl.query.InvalidProperty):
        reader.read_inventory_config(content, cid, {}, deadline=INF)
    assert collector.RetrievePropertiesEx.call_count == 2
    assert (
        reader.read_inventory_config(content, cid, {}, deadline=INF).cluster_path
        == "configuration"
    )


def test_overview_pagination_and_exact_deadline_cancel(monkeypatch):
    vm = vim.VirtualMachine("vm")
    content, pc = pc_content(page(vm_overview(vm), token="next"))
    pc.ContinueRetrievePropertiesEx.return_value = page()
    destroyed = Mock()
    monkeypatch.setattr(vim.view.ContainerView, "Destroy", destroyed)
    ticks = iter([19.999, 20.0])
    monkeypatch.setattr(reader, "monotonic", lambda: next(ticks))
    with pytest.raises(reader.ConfigReadTimeout):
        reader.read_overview(
            content, reader.overview_paths("configurationEx"), deadline=20.0
        )
    pc.CancelRetrievePropertiesEx.assert_called_once_with("next")
    pc.ContinueRetrievePropertiesEx.assert_not_called()
    destroyed.assert_called_once()
    assert pc.RetrievePropertiesEx.call_args.kwargs["options"].maxObjects == 1000

    content, pc = pc_content(page(vm_overview(vm), token="next"))
    pc.ContinueRetrievePropertiesEx.return_value = page(raw(vim.HostSystem("h"), {}))
    monkeypatch.setattr(reader, "monotonic", lambda: 0)
    rows, _ = reader.read_overview(
        content, reader.overview_paths("configurationEx"), deadline=1
    )
    assert [r.ref._moId for r in rows] == ["vm", "h"]
    pc.ContinueRetrievePropertiesEx.assert_called_once_with("next")
    assert destroyed.call_count == 2


@pytest.fixture(autouse=True)
def no_view_rpc(monkeypatch):
    monkeypatch.setattr(vim.view.ContainerView, "Destroy", lambda self: None)


def test_vm_details_selection_uses_original_refs_and_stage_two_version(monkeypatch):
    ids = [
        "new-z",
        "v-b",
        "same",
        "different-newer",
        "v-a",
        "new-a",
        "different-z",
        "different-old",
        "different-a",
        "cold",
        "no-generation",
        "template",
        "empty-generation",
    ]
    refs = {name: vim.VirtualMachine(name) for name in ids}
    overview = {
        **{name: vm_overview(ref) for name, ref in refs.items()},
        "cold": vm_overview(
            refs["cold"], **{"runtime.connectionState": "disconnected"}
        ),
        "no-generation": vm_overview(refs["no-generation"], None),
        "template": vm_overview(refs["template"], **{"summary.config.template": True}),
        "empty-generation": raw(
            refs["empty-generation"], {"runtime.connectionState": "connected"}
        ),
    }
    later = NOW + timedelta(seconds=1)
    baselines = {
        "same": ConfigBaseline("v1", 1, NOW),
        "v-a": ConfigBaseline("v1", 0, NOW),
        "v-b": ConfigBaseline("v1", 0, NOW),
        "different-z": ConfigBaseline("old", 1, NOW),
        "different-a": ConfigBaseline("old", 1, NOW),
        "different-old": ConfigBaseline("old", 1, NOW - timedelta(days=1)),
        "different-newer": ConfigBaseline("old", 1, later),
        "cold": ConfigBaseline("v1", 1, NOW),
    }
    order = [
        "v-a",
        "v-b",
        "different-old",
        "different-a",
        "different-z",
        "different-newer",
        "new-a",
        "new-z",
    ]
    content, pc = pc_content(
        page(*overview.values()),
        page(
            *(raw(refs[name], vm_details(version="v2")) for name in order),
        ),
    )
    monkeypatch.setattr(
        reader,
        "utcnow",
        lambda: NOW + timedelta(seconds=pc.RetrievePropertiesEx.call_count),
    )
    result = reader.read_inventory_config(content, uuid4(), baselines, deadline=INF)
    assert result.started_at == NOW
    assert result.observed_at == NOW + timedelta(seconds=2)
    call = pc.RetrievePropertiesEx.call_args.kwargs["specSet"][0]
    assert list(call.propSet[0].pathSet) == list(VM_DETAIL_PATHS)
    assert [spec.obj._moId for spec in call.objectSet] == order
    assert all(spec.obj is refs[moid] for spec, moid in zip(call.objectSet, order))
    assert all(not spec.skip and not spec.selectSet for spec in call.objectSet)
    assert result.change_versions["new-a"] == "v2"
    assert result.unchanged_vms == {"same"}
    assert result.carry_over == {
        (name, "vm_config") for name in ("cold", "no-generation", "empty-generation")
    }
    assert "template" not in result.objects
    assert content.viewManager.CreateContainerView.call_count == 1


@pytest.mark.parametrize("retry_success", [True, False])
def test_managed_object_not_found_removes_only_vm_and_limits_to_ten_retries(
    retry_success,
):
    refs = [vim.VirtualMachine(f"vm-{i}") for i in range(12)]
    removed = 10 if retry_success else 11
    errors = [vmodl.fault.ManagedObjectNotFound(obj=ref) for ref in refs[:removed]]
    content, pc = pc_content(
        *errors, page(*(raw(ref, vm_details()) for ref in refs[removed:]))
    )
    if retry_success:
        result = reader.read_vm_details(content, refs, deadline=INF)
        assert result.removed == {ref._moId for ref in refs[:10]}
        assert result.rows.keys() == {ref._moId for ref in refs[10:]}
    else:
        with pytest.raises(vmodl.fault.ManagedObjectNotFound):
            reader.read_vm_details(content, refs, deadline=INF)
    assert pc.RetrievePropertiesEx.call_count == 11
    for i, call in enumerate(pc.RetrievePropertiesEx.call_args_list):
        assert [spec.obj for spec in call.kwargs["specSet"][0].objectSet] == refs[i:]


def test_managed_object_not_found_outside_batch_is_failure():
    bad = vmodl.fault.ManagedObjectNotFound(obj=vim.VirtualMachine("unrelated"))
    content, pc = pc_content(bad)
    with pytest.raises(vmodl.fault.ManagedObjectNotFound):
        reader.read_vm_details(content, [vim.VirtualMachine("vm")], deadline=INF)
    assert pc.RetrievePropertiesEx.call_count == 1


def test_vm_batch_size_and_deadline_defer_only_not_yet_read(monkeypatch):
    refs = [vim.VirtualMachine(f"vm-{i:03}") for i in range(401)]
    content, pc = pc_content(page(*(raw(ref, vm_details()) for ref in refs[:200])))
    ticks = iter([9.999, 10.0])
    monkeypatch.setattr(reader, "monotonic", lambda: next(ticks))
    result = reader.read_vm_details(content, refs, deadline=10.0)
    pc.RetrievePropertiesEx.assert_called_once()
    assert len(pc.RetrievePropertiesEx.call_args.kwargs["specSet"][0].objectSet) == 200
    assert result.rows.keys() == {ref._moId for ref in refs[:200]}
    assert result.deferred == {ref._moId for ref in refs[200:]}
    assert not result.removed


@pytest.mark.parametrize(
    "mode", ["null", "absent", "missing", "vm-removed", "deferred"]
)
def test_unread_detailed_vm_is_distinguished_from_deferred(mode):
    ref = vim.VirtualMachine("vm")
    props = vm_details()
    path = "config.hardware.device"
    missing = set()
    details = reader.VMDetails()
    if mode == "null":
        props[path] = None
    elif mode == "absent":
        del props[path]
    elif mode == "missing":
        missing.add(path)
    if mode == "deferred":
        details.deferred.add("vm")
    elif mode == "vm-removed":
        details.removed.add("vm")
    else:
        details.rows["vm"] = PropertyRow(ref, props, missing)
    observation = ConfigObservation("vc", NOW, NOW, "configurationEx")
    reader.normalize_details(observation, ["vm"], details)
    assert not observation.values
    if mode == "deferred":
        assert observation.deferred_vms == {"vm"}
        assert not observation.unread_vms and not observation.carry_over
    else:
        assert not observation.deferred_vms
        assert observation.unread_vms == {"vm"}
        assert observation.carry_over == {("vm", "vm_config")}


def test_value_hash_uses_sorted_compact_utf8_json():
    value = {"z": ["日本語", True], "a": {"y": 2, "x": None}}
    canonical = '{"a":{"x":null,"y":2},"z":["日本語",true]}'
    assert value_hash(value) == sha256(canonical.encode("utf-8")).hexdigest()


def test_snapshot_chain_uses_base_disk_and_only_reports_changes_to_its_configuration():
    base = Obj(thinProvisioned=True, diskMode="persistent", uuid="base-uuid")
    disk = VirtualDisk(key=2000, deviceInfo=Obj(label="Disk"), backing=base)
    original = normalize_vm(vm_details(disk))
    assert original["devices"]["disk:2000"]["uuid"] == "base-uuid"
    disk.backing = Obj(
        diskMode="redo",
        uuid="delta-uuid",
        parent=Obj(
            thinProvisioned=False,
            diskMode="delta",
            uuid="intermediate-uuid",
            parent=base,
        ),
    )
    snapshot = normalize_vm(vm_details(disk))
    assert snapshot["devices"]["disk:2000"]["uuid"] == "base-uuid"
    assert value_hash(snapshot) == value_hash(original)
    assert not list(diff_config("vm_config", original, snapshot))
    disk.backing = base
    assert normalize_vm(vm_details(disk)) == original

    base.thinProvisioned = False
    base.diskMode = "independent_persistent"
    disk.backing = Obj(parent=base)
    modified = normalize_vm(vm_details(disk))
    assert {
        diff.attribute for diff in diff_config("vm_config", original, modified)
    } == {
        "thin",
        "disk_mode",
    }


@pytest.mark.parametrize(
    ("raw_uuid", "expected"),
    [
        (" 6000C29A-ABCD ", "6000c29a-abcd"),
        ("6000c29a-abcd", "6000c29a-abcd"),
        ("", None),
        ("   ", None),
        (None, None),
        (12, None),
    ],
)
def test_disk_uuid_is_trimmed_lowercased_and_empty_is_none(raw_uuid, expected):
    base = Obj(thinProvisioned=True, diskMode="persistent", uuid=raw_uuid)
    disk = VirtualDisk(key=2000, deviceInfo=Obj(label="Disk"), backing=base)
    assert normalize_vm(vm_details(disk))["devices"]["disk:2000"]["uuid"] == expected


def test_disk_uuid_case_and_spacing_do_not_record_a_replacement():
    base = Obj(thinProvisioned=True, diskMode="persistent", uuid="6000c29a-abcd")
    disk = VirtualDisk(key=2000, deviceInfo=Obj(label="Disk"), backing=base)
    before = normalize_vm(vm_details(disk))
    base.uuid = " 6000C29A-ABCD "
    after = normalize_vm(vm_details(disk))
    assert value_hash(after) == value_hash(before)
    assert not list(diff_config("vm_config", before, after))


def test_disk_backing_cycles_unreadable_parent_and_depth_limit():
    from vcenter_event_assistant.collectors.config_values import disk_backing_root

    class CyclicBacking:
        reads = 0

        @property
        def parent(self):
            self.reads += 1
            return self

    class UnreadableBacking:
        @property
        def parent(self):
            raise RuntimeError("参照できない")

    def observe(backing):
        disk = VirtualDisk(key=2000, backing=backing)
        vm = vim.VirtualMachine("vm")
        props = vm_details(disk, version="v2")
        observation = ConfigObservation("vc", NOW, NOW, "configurationEx")
        reader.normalize_details(
            observation,
            ["vm"],
            reader.VMDetails({"vm": PropertyRow(vm, props, set())}),
        )
        return observation

    base = Obj(thinProvisioned=True, diskMode="persistent")
    chain = base
    for _ in range(64):
        chain = Obj(parent=chain)
    assert disk_backing_root(chain) is base
    stored = observe(chain).values["vm", "vm_config"]["devices"]["disk:2000"]
    assert stored["thin"] is True and stored["disk_mode"] == "persistent"

    cycle = CyclicBacking()
    for invalid in (cycle, UnreadableBacking(), chain, None):
        backing = (
            Obj(parent=invalid, thinProvisioned=True, diskMode="delta")
            if invalid is not None
            else None
        )
        observation = observe(backing)
        assert observation.unread_vms == {"vm"}
        assert observation.carry_over == {("vm", "vm_config")}
        assert not observation.values and not observation.change_versions
    assert cycle.reads == 1


@pytest.mark.parametrize(
    "path",
    [
        "config.changeVersion",
        "config.hardware.numCPU",
        "config.hardware.memoryMB",
        "config.hardware.device",
    ],
)
def test_each_required_vm_detail_is_checked(path):
    vm = vim.VirtualMachine("vm")
    props = vm_details()
    del props[path]
    config = ConfigObservation("vc", NOW, NOW, "configurationEx")
    reader.normalize_details(
        config,
        ["vm"],
        reader.VMDetails(
            {
                "vm": PropertyRow(vm, props, set()),
            }
        ),
    )
    assert config.unread_vms == {"vm"} and config.carry_over == {("vm", "vm_config")}
    assert not config.values


def test_disk_uuid_replacement_rule_does_not_apply_to_nic_keys():
    # UUID が入力にあっても NIC は項目単位で比較する。
    old = {"devices": {"nic:4000": {"label": "NIC", "uuid": "old"}}}
    new = {"devices": {"nic:4000": {"label": "NIC", "uuid": "new"}}}
    (diff,) = diff_config("vm_config", old, new)
    assert (diff.element, diff.attribute, diff.old_value, diff.new_value) == (
        "nic:4000",
        "uuid",
        '"old"',
        '"new"',
    )


def _assert_serializes(spec):
    """偽の collector は直列化しないので、実機に送るときと同じ直列化を通す。"""
    for prop in spec.propSet:
        assert isinstance(prop.pathSet, list)
        xml = SoapAdapter.Serialize(prop)
        for path in prop.pathSet:
            assert f"<pathSet>{path}</pathSet>".encode() in xml


@pytest.mark.parametrize("cluster_path", ["configurationEx", "configuration"])
def test_overview_request_serializes_for_the_soap_call(no_view_rpc, cluster_path):
    content, pc = pc_content(page())
    reader.read_overview(content, reader.overview_paths(cluster_path), deadline=INF)
    _assert_serializes(pc.RetrievePropertiesEx.call_args.kwargs["specSet"][0])


def test_vm_details_request_serializes_for_the_soap_call():
    ref = vim.VirtualMachine("vm-1")
    content, pc = pc_content(page(raw(ref, vm_details())))
    reader.read_vm_details(content, [ref], deadline=INF)
    _assert_serializes(pc.RetrievePropertiesEx.call_args.kwargs["specSet"][0])
