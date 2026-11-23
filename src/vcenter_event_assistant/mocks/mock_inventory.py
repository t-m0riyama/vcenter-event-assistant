"""モックモードとシードで共有するインベントリの構成。"""

from datetime import datetime

from vcenter_event_assistant.collectors.inventory import (
    InventoryObjectData,
    InventoryObservation,
)
from vcenter_event_assistant.mocks.mock_collectors import MOCK_HOST_MOID, MOCK_VM_MOID

MOCK_INVENTORY_SLOT_SECONDS = 30 * 60
MOCK_INSTANCE_UUID = "3a7754a0-6b11-42b7-bef5-d97c254dc3ff"

SCREENSHOT_VCENTER_NAME = "screenshot-e2e-vc"
SCREENSHOT_HOSTS = (("host-9001", "demo-esxi-01"), ("host-9002", "demo-esxi-02"))
SCREENSHOT_VMS = (
    ("vm-9001", "demo-vm-01"),
    ("vm-9002", "demo-vm-02"),
    ("vm-9003", "demo-vm-03"),
)
SCREENSHOT_DATASTORE = ("datastore-1001", "demo-datastore")

_CLUSTER = "domain-c-mock-01"
_HOSTS = ((MOCK_HOST_MOID, "esxi-mock-01"), ("host-mock-02", "esxi-mock-02"))
_VMS = (
    (MOCK_VM_MOID, "vm-mock-web-01"),
    ("vm-mock-02", "vm-mock-app-02"),
    ("vm-mock-03", "vm-mock-db-03"),
)
_DATASTORES = (
    ("datastore-mock-01", "mock-datastore"),
    ("datastore-mock-02", "mock-datastore-02"),
)
_NETWORKS = ("network-mock-01", "dvportgroup-mock-02")


def mock_inventory(
    now: datetime, *, vcenter_name: str = "", screenshot_before_move: bool = False
) -> InventoryObservation:
    """通常は 30 分ごとに VM が移り、スクリーンショット用には移動方向を固定する。"""
    hosts, vms, datastores = _HOSTS, _VMS, _DATASTORES
    if vcenter_name == SCREENSHOT_VCENTER_NAME:
        moving_host = 0 if screenshot_before_move else 1
        # タイムラインとグラフにある対象の moid を使う。
        hosts, vms, datastores = (
            SCREENSHOT_HOSTS,
            SCREENSHOT_VMS,
            (SCREENSHOT_DATASTORE, _DATASTORES[1]),
        )
    else:
        moving_host = (int(now.timestamp()) // MOCK_INVENTORY_SLOT_SECONDS) % len(hosts)

    objects = {
        _CLUSTER: InventoryObjectData("ClusterComputeResource", "mock-cluster"),
        _NETWORKS[0]: InventoryObjectData("Network", "mock-management"),
        _NETWORKS[1]: InventoryObjectData(
            "DistributedVirtualPortgroup", "mock-workload"
        ),
    }
    for kind, entries in (
        ("HostSystem", hosts),
        ("VirtualMachine", vms),
        ("Datastore", datastores),
    ):
        objects.update(
            {moid: InventoryObjectData(kind, name) for moid, name in entries}
        )

    relations = {("host_cluster", host, _CLUSTER) for host, _ in hosts}
    relations.update(
        ("host_datastore", host, ds) for host, _ in hosts for ds, _ in datastores
    )
    relations.update(
        ("host_network", host, net) for host, _ in hosts for net in _NETWORKS
    )
    for index, (vm, _) in enumerate(vms):
        host_index = moving_host if index == 0 else index % len(hosts)
        relations.add(("vm_host", vm, hosts[host_index][0]))
        relations.add(("vm_datastore", vm, datastores[index % len(datastores)][0]))
        relations.add(("vm_network", vm, _NETWORKS[1]))
    return InventoryObservation(MOCK_INSTANCE_UUID, objects, relations, set())
