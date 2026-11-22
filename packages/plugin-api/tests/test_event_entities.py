"""イベントの対象を、実際の pyVmomi の値と偽オブジェクトで確かめる。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from vcenter_event_assistant_plugin_api import limits, testing, vmware


@pytest.fixture
def vim() -> Any:
    return pytest.importorskip("pyVmomi").vim


@pytest.fixture
def args(vim: Any) -> dict[str, Any]:
    def argument(kind: str, attr: str, ref: Any, name: str) -> Any:
        return getattr(vim.event, f"{kind}EventArgument")(name=name, **{attr: ref})

    return {
        "vm": argument("Vm", "vm", vim.VirtualMachine("vm-1"), "web"),
        "host": argument("Host", "host", vim.HostSystem("host-1"), "esx01"),
        "otherHost": argument("Host", "host", vim.HostSystem("host-2"), "esx02"),
        "computeResource": argument(
            "ComputeResource",
            "computeResource",
            vim.ClusterComputeResource("domain-c1"),
            "cluster",
        ),
        "datacenter": argument(
            "Datacenter", "datacenter", vim.Datacenter("dc-1"), "dc"
        ),
        "datastore": argument("Datastore", "datastore", vim.Datastore("ds-1"), "store"),
        "dvs": argument(
            "Dvs", "dvs", vim.VmwareDistributedVirtualSwitch("dvs-1"), "switch"
        ),
        "folder": argument("Folder", "folder", vim.Folder("group-1"), "folder"),
        "pool": argument(
            "ResourcePool", "resourcePool", vim.ResourcePool("resgroup-1"), "pool"
        ),
        "entity": argument(
            "ManagedEntity", "entity", vim.HostSystem("host-1"), "esx01"
        ),
        "source": argument("ManagedEntity", "entity", vim.Folder("group-1"), "folder"),
        "hostOutOfSync": vim.event.DvsOutOfSyncHostArgument(
            outOfSyncHost=argument("Host", "host", vim.HostSystem("host-2"), "esx02")
        ),
        "connectee": vim.dvs.PortConnectee(connectedEntity=vim.VirtualMachine("vm-1")),
        "info": vim.TaskInfo(
            entity=vim.HostSystem("host-2"),
            entityName="esx02",
            locked=[vim.HostSystem("host-3")],
        ),
    }


_HOST = "host computeResource datacenter"
_VM = f"vm {_HOST}"
_CLUSTER = "computeResource datacenter"
_DVS = "dvs datacenter"


@pytest.mark.parametrize(
    ("event_type", "base", "children", "primary"),
    [
        ("HostConnectionLostEvent", _HOST, {}, "host"),
        ("VmPoweredOnEvent", _VM, {}, "vm"),
        (
            "VmMigratedEvent",
            _VM,
            dict(
                sourceHost="otherHost",
                sourceDatastore="datastore",
                sourceDatacenter="datacenter",
            ),
            "vm",
        ),
        (
            "DrsVmMigratedEvent",
            _VM,
            dict(
                sourceHost="otherHost",
                sourceDatastore="datastore",
                sourceDatacenter="datacenter",
            ),
            "vm",
        ),
        (
            "VmBeingMigratedEvent",
            _VM,
            dict(
                destHost="otherHost",
                destDatastore="datastore",
                destDatacenter="datacenter",
            ),
            "vm",
        ),
        ("VmPowerOffOnIsolationEvent", _VM, {"isolatedHost": "otherHost"}, "vm"),
        ("MigrationHostErrorEvent", _VM, {"dstHost": "otherHost"}, "vm"),
        ("DasHostFailedEvent", _CLUSTER, {"failedHost": "otherHost"}, "failedHost"),
        (
            "DasHostIsolatedEvent",
            _CLUSTER,
            {"isolatedHost": "otherHost"},
            "isolatedHost",
        ),
        ("DatastoreRemovedOnHostEvent", _HOST, {"datastore": "datastore"}, "datastore"),
        (
            "DatastoreFileMovedEvent",
            "datacenter",
            dict(datastore="datastore", sourceDatastore="datastore"),
            "datastore",
        ),
        ("ClusterCreatedEvent", _CLUSTER, {"parent": "folder"}, "computeResource"),
        ("DatacenterCreatedEvent", "datacenter", {"parent": "folder"}, "datacenter"),
        ("DvsCreatedEvent", _DVS, {"parent": "folder"}, "dvs"),
        ("DvsMergedEvent", _DVS, dict(sourceDvs="dvs", destinationDvs="dvs"), "dvs"),
        (
            "ResourcePoolCreatedEvent",
            _CLUSTER,
            dict(resourcePool="pool", parent="pool"),
            "resourcePool",
        ),
        (
            "ResourcePoolMovedEvent",
            _CLUSTER,
            dict(resourcePool="pool", oldParent="pool", newParent="pool"),
            "resourcePool",
        ),
        ("DvsHostJoinedEvent", _DVS, {"hostJoined": "otherHost"}, "hostJoined"),
        ("DvsHostStatusUpdated", _DVS, {"hostMember": "otherHost"}, "hostMember"),
        (
            "DvsHostWentOutOfSyncEvent",
            _DVS,
            {"hostOutOfSync": "hostOutOfSync"},
            "hostOutOfSync",
        ),
        ("DvsPortConnectedEvent", _DVS, {"connectee": "connectee"}, "dvs"),
        ("TaskEvent", "vm", {"info": "info"}, "vm"),
        ("TaskEvent", "", {"info": "info"}, "info.entity"),
        (
            "HostWwnConflictEvent",
            _HOST,
            dict(conflictedVms=["vm"], conflictedHosts=["otherHost", "host"]),
            "host",
        ),
        (
            "LockerReconfiguredEvent",
            "",
            dict(oldDatastore="datastore", newDatastore="datastore"),
            "newDatastore",
        ),
        (
            "AlarmStatusChangedEvent",
            "host",
            dict(entity="entity", source="source"),
            "entity",
        ),
        ("ScheduledTaskCompletedEvent", "host", {"entity": "entity"}, "entity"),
        ("PermissionAddedEvent", "host", {"entity": "entity"}, "entity"),
        (
            "ProfileReferenceHostChangedEvent",
            "",
            dict(
                referenceHost=lambda vim: vim.HostSystem("host-2"),
                referenceHostName=lambda _: "esx02",
            ),
            "referenceHost",
        ),
        (
            "VmDeployFailedEvent",
            _VM,
            {"destDatastore": lambda vim: vim.event.EntityEventArgument(name="target")},
            "vm",
        ),
        (
            "EventEx",
            "host",
            dict(
                objectId=lambda _: "host-2",
                objectType=lambda vim: vim.HostSystem,
                objectName=lambda _: "esx02",
            ),
            "object",
        ),
        (
            "ExtendedEvent",
            "host",
            {
                "managedObject": lambda vim: vim.HostSystem("host-2"),
            },
            "managedObject",
        ),
        ("DatacenterRenamedEvent", "datacenter", {}, "datacenter"),
    ],
)
def test_primary_role_for_representative_events(
    vim: Any,
    args: dict[str, Any],
    event_type: str,
    base: str,
    children: dict[str, Any],
    primary: str,
) -> None:
    attrs = {role: args[role] for role in base.split()}
    for role, value in children.items():
        if callable(value):
            attrs[role] = value(vim)
        elif isinstance(value, list):
            attrs[role] = [args[key] for key in value]
        else:
            attrs[role] = args[value]
    event = getattr(vim.event, event_type)(**attrs)

    entities = vmware.event_entities(event)

    assert [entity.role for entity in entities if entity.is_primary] == [primary]


def _rows(event: Any) -> set[tuple[Any, ...]]:
    return {
        (e.role, e.position, e.entity_type, e.entity_moid, e.entity_name)
        for e in vmware.event_entities(event)
    }


@pytest.mark.parametrize("vm_name", [None, ""])
def test_empty_vm_argument_does_not_displace_the_host(
    vim: Any, vm_name: str | None
) -> None:
    vm = (
        vim.event.VmEventArgument()
        if vm_name is None
        else vim.event.VmEventArgument(name=vm_name)
    )
    event = vim.event.VmPoweredOnEvent(
        vm=vm,
        host=vim.event.HostEventArgument(host=vim.HostSystem("host-1"), name="esx"),
    )

    assert vmware.event_entities(event) == (
        vmware.EventEntityInput("host", 0, "HostSystem", "host-1", "esx", True),
    )


def test_migration_keeps_all_related_entities(vim: Any, args: dict[str, Any]) -> None:
    event = vim.event.VmMigratedEvent(
        vm=args["vm"],
        host=args["host"],
        computeResource=args["computeResource"],
        datacenter=args["datacenter"],
        sourceHost=args["otherHost"],
        sourceDatastore=args["datastore"],
        sourceDatacenter=args["datacenter"],
    )

    assert _rows(event) == {
        ("vm", 0, "VirtualMachine", "vm-1", "web"),
        ("host", 0, "HostSystem", "host-1", "esx01"),
        ("computeResource", 0, "ClusterComputeResource", "domain-c1", "cluster"),
        ("datacenter", 0, "Datacenter", "dc-1", "dc"),
        ("sourceHost", 0, "HostSystem", "host-2", "esx02"),
        ("sourceDatastore", 0, "Datastore", "ds-1", "store"),
        ("sourceDatacenter", 0, "Datacenter", "dc-1", "dc"),
    }


def test_wwn_conflict_preserves_array_positions(vim: Any, args: dict[str, Any]) -> None:
    event = vim.event.HostWwnConflictEvent(
        host=args["host"],
        conflictedVms=[args["vm"]],
        conflictedHosts=[
            args["otherHost"],
            args["host"],
        ],
    )

    assert _rows(event) == {
        ("host", 0, "HostSystem", "host-1", "esx01"),
        ("conflictedVms", 0, "VirtualMachine", "vm-1", "web"),
        ("conflictedHosts", 0, "HostSystem", "host-2", "esx02"),
        ("conflictedHosts", 1, "HostSystem", "host-1", "esx01"),
    }


def test_alarm_keeps_entity_and_source(vim: Any, args: dict[str, Any]) -> None:
    event = vim.event.AlarmStatusChangedEvent(
        entity=args["entity"], source=args["source"]
    )

    assert _rows(event) == {
        ("entity", 0, "HostSystem", "host-1", "esx01"),
        ("source", 0, "Folder", "group-1", "folder"),
    }


@pytest.mark.parametrize("as_string", [False, True])
def test_event_ex_object(vim: Any, as_string: bool) -> None:
    attrs = {"objectId": "host-1", "objectName": "esx01"}
    event = (
        testing.fake_event(event_type="EventEx", objectType="vim.HostSystem", **attrs)
        if as_string
        else vim.event.EventEx(objectType=vim.HostSystem, **attrs)
    )

    assert _rows(event) == {("object", 0, "HostSystem", "host-1", "esx01")}


def test_event_ex_allows_name_only_and_rejects_other_object_types(vim: Any) -> None:
    assert _rows(vim.event.EventEx(objectName="esx01")) == {
        ("object", 0, None, None, "esx01"),
    }
    assert (
        vmware.event_entities(
            vim.event.EventEx(objectId="task-1", objectType=vim.Task, objectName="task")
        )
        == ()
    )


@pytest.mark.parametrize("object_type", [123, str])
@pytest.mark.parametrize(
    ("object_id", "name"),
    [("host-1", None), (None, "esx01")],
)
def test_event_ex_keeps_objects_with_unknown_types(
    object_type: object,
    object_id: str | None,
    name: str | None,
) -> None:
    event = testing.fake_event(
        event_type="EventEx",
        objectType=object_type,
        objectId=object_id,
        objectName=name,
    )

    assert vmware.event_entities(event) == (
        vmware.EventEntityInput("object", 0, None, object_id, name, True),
    )


def test_event_ex_rejects_a_known_type_outside_inventory() -> None:
    event = testing.fake_event(
        event_type="EventEx", objectType="vim.Task", objectId="task-1"
    )

    assert vmware.event_entities(event) == ()


def test_extended_event_uses_the_other_role_name_for_the_same_moid(
    vim: Any,
    args: dict[str, Any],
) -> None:
    event = vim.event.ExtendedEvent(
        managedObject=vim.HostSystem("host-1"), host=args["host"]
    )

    assert _rows(event) == {
        ("managedObject", 0, "HostSystem", "host-1", "esx01"),
        ("host", 0, "HostSystem", "host-1", "esx01"),
    }
    assert _rows(vim.event.ExtendedEvent(managedObject=vim.HostSystem("host-1"))) == {
        ("managedObject", 0, "HostSystem", "host-1", None),
    }
    assert (
        vmware.event_entities(vim.event.ExtendedEvent(managedObject=vim.Task("task-1")))
        == ()
    )


def test_profile_reference_host_uses_the_event_name(vim: Any) -> None:
    event = vim.event.ProfileReferenceHostChangedEvent(
        referenceHost=vim.HostSystem("host-2"), referenceHostName="esx02"
    )
    assert _rows(event) == {("referenceHost", 0, "HostSystem", "host-2", "esx02")}


def test_task_event_reads_entity_but_does_not_include_locks(
    vim: Any,
    args: dict[str, Any],
) -> None:
    assert _rows(vim.event.TaskEvent(info=args["info"])) == {
        ("info.entity", 0, "HostSystem", "host-2", "esx02"),
    }


def test_dvs_out_of_sync_array_and_connectee(vim: Any, args: dict[str, Any]) -> None:
    out_of_sync = vim.event.OutOfSyncDvsHost(
        dvs=args["dvs"],
        hostOutOfSync=[
            vim.event.DvsOutOfSyncHostArgument(),
            args["hostOutOfSync"],
            vim.event.DvsOutOfSyncHostArgument(outOfSyncHost=args["host"]),
        ],
    )
    assert _rows(out_of_sync) == {
        ("dvs", 0, "VmwareDistributedVirtualSwitch", "dvs-1", "switch"),
        ("hostOutOfSync", 1, "HostSystem", "host-2", "esx02"),
        ("hostOutOfSync", 2, "HostSystem", "host-1", "esx01"),
    }
    assert [
        (e.role, e.position) for e in vmware.event_entities(out_of_sync) if e.is_primary
    ] == [("hostOutOfSync", 1)]
    assert _rows(
        vim.event.DvsPortConnectedEvent(dvs=args["dvs"], connectee=args["connectee"])
    ) == {
        ("dvs", 0, "VmwareDistributedVirtualSwitch", "dvs-1", "switch"),
        ("connectee", 0, "VirtualMachine", "vm-1", None),
    }


def test_non_inventory_arguments_and_faults_are_ignored(vim: Any) -> None:
    fault = pytest.importorskip("pyVmomi").vmodl.fault.ManagedObjectNotFound(
        obj=vim.HostSystem("host-1")
    )
    events = [
        vim.event.AlarmStatusChangedEvent(
            alarm=vim.event.AlarmEventArgument(name="alarm")
        ),
        vim.event.ScheduledTaskCompletedEvent(
            scheduledTask=vim.event.ScheduledTaskEventArgument(name="task")
        ),
        vim.event.ProfileReferenceHostChangedEvent(
            profile=vim.event.ProfileEventArgument(name="profile")
        ),
        vim.event.PermissionAddedEvent(role=vim.event.RoleEventArgument(name="role")),
        vim.event.EventEx(fault=fault),
        vim.event.VmDeployFailedEvent(reason=fault),
    ]

    assert [vmware.event_entities(event) for event in events] == [()] * len(events)


def test_managed_object_properties_are_never_fetched(vim: Any) -> None:
    class CountingStub:
        def __init__(self) -> None:
            self.calls = 0

        def InvokeAccessor(self, *args: Any) -> Any:  # noqa: N802
            self.calls += 1
            raise RuntimeError("vCenter accessor must not be called")

        def InvokeMethod(self, *args: Any) -> Any:  # noqa: N802
            self.calls += 1
            raise RuntimeError("vCenter method must not be called")

    stub = CountingStub()
    host = vim.HostSystem("host-10", stub)
    host_arg = vim.event.HostEventArgument(host=host, name="esx10")

    assert vmware.event_entities(host) == ()
    assert _rows(vim.event.ProfileReferenceHostChangedEvent(referenceHost=host)) == {
        ("referenceHost", 0, "HostSystem", "host-10", None),
    }
    assert _rows(vim.event.HostConnectionLostEvent(host=host_arg)) == {
        ("host", 0, "HostSystem", "host-10", "esx10"),
    }
    assert _rows(
        vim.event.DvsPortConnectedEvent(
            connectee=vim.dvs.PortConnectee(connectedEntity=host)
        )
    ) == {("connectee", 0, "HostSystem", "host-10", None)}
    assert _rows(
        vim.event.TaskEvent(info=vim.TaskInfo(entity=host, entityName="esx10"))
    ) == {
        ("info.entity", 0, "HostSystem", "host-10", "esx10"),
    }
    assert _rows(vim.event.ExtendedEvent(managedObject=host)) == {
        ("managedObject", 0, "HostSystem", "host-10", None),
    }
    assert _rows(
        vim.event.AlarmStatusChangedEvent(
            entity=vim.event.ManagedEntityEventArgument(entity=host, name="esx10")
        )
    ) == {("entity", 0, "HostSystem", "host-10", "esx10")}
    assert _rows(vim.event.HostWwnConflictEvent(conflictedHosts=[host_arg])) == {
        ("conflictedHosts", 0, "HostSystem", "host-10", "esx10"),
    }
    assert _rows(
        vim.event.OutOfSyncDvsHost(
            hostOutOfSync=[vim.event.DvsOutOfSyncHostArgument(outOfSyncHost=host_arg)]
        )
    ) == {("hostOutOfSync", 0, "HostSystem", "host-10", "esx10")}
    assert _rows(
        vim.event.ExtendedEvent(
            managedObject=host,
            host=vim.event.HostEventArgument(
                host=vim.HostSystem("host-10", stub),
                name="esx10",
            ),
        )
    ) == {
        ("host", 0, "HostSystem", "host-10", "esx10"),
        ("managedObject", 0, "HostSystem", "host-10", "esx10"),
    }
    assert stub.calls == 0


def test_fake_event_has_the_same_entities_as_pyvmomi(
    vim: Any, args: dict[str, Any]
) -> None:
    event = testing.fake_event(
        event_type="HostConnectionLostEvent",
        host=testing.fake_event_argument(testing.fake_host("host-1", "esx01")),
    )
    assert vmware.event_entities(event) == vmware.event_entities(
        vim.event.HostConnectionLostEvent(host=args["host"])
    )


@pytest.mark.parametrize(
    ("raw_moid", "expected"), [(0, "0"), (123, "123"), (None, None), ("", None)]
)
def test_managed_moid_is_converted_to_text(
    raw_moid: object, expected: str | None
) -> None:
    event = testing.fake_event(host=SimpleNamespace(_moId=raw_moid, name="esx01"))

    assert _rows(event) == {("host", 0, None, expected, "esx01")}


@pytest.mark.parametrize("raw_moid", [None, ""])
def test_managed_object_without_moid_or_name_is_ignored(raw_moid: object) -> None:
    event = testing.fake_event(
        host=SimpleNamespace(_moId=raw_moid, _wsdlName="HostSystem")
    )

    assert vmware.event_entities(event) == ()


def test_fake_event_argument_accepts_a_managed_object_without_an_instance_dict() -> (
    None
):
    class SlottedHost:
        __slots__ = ()
        _moId = "host-10"
        _wsdlName = "HostSystem"

    host = SlottedHost()
    argument = testing.fake_event_argument(host)

    assert argument.name is None
    assert argument.host is host
    assert _rows(testing.fake_event(host=argument)) == {
        ("host", 0, "HostSystem", "host-10", None),
    }


def test_overlong_values_keep_the_entity(monkeypatch: pytest.MonkeyPatch) -> None:
    event = testing.fake_event(
        host=SimpleNamespace(
            _moId="x" * (limits.MAX_ENTITY_MOID + 1),
            _wsdlName="HostSystem",
            name="名" * (limits.MAX_ENTITY_NAME + 1),
        )
    )
    # 許可された型名で列長を超える分岐を通す。
    monkeypatch.setattr(limits, "MAX_EVENT_ENTITY_TYPE", len("HostSystem") - 1)

    assert _rows(event) == {
        ("host", 0, None, None, "名" * (limits.MAX_ENTITY_NAME - 1) + "…")
    }


def test_unknown_fake_type_and_name_only_arguments_are_kept() -> None:
    event = testing.fake_event(
        entity=testing.FakeManagedObject("unknown-1", name="untyped"),
        host=SimpleNamespace(
            _wsdlName="HostEventArgument", name="name only", host=None
        ),
    )
    assert _rows(event) == {
        ("entity", 0, None, "unknown-1", "untyped"),
        ("host", 0, None, None, "name only"),
    }


def test_primary_priority_is_independent_of_attribute_order() -> None:
    host = testing.fake_host()
    events = [
        (testing.fake_event(zChild=host, aChild=host), "aChild"),
        (
            testing.fake_event(
                aChild=host, datastore=host, isolatedHost=host, failedHost=host
            ),
            "failedHost",
        ),
        (testing.fake_event(dstHost=host, conflictedHosts=[host]), "conflictedHosts"),
    ]
    for event, primary in events:
        assert [e.role for e in vmware.event_entities(event) if e.is_primary] == [
            primary
        ]
