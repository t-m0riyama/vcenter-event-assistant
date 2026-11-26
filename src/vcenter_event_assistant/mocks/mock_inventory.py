"""モックモードとシードで共有するインベントリの構成。"""

from datetime import datetime

from vcenter_event_assistant.auth.timeutil import utcnow
from vcenter_event_assistant.collectors.config_values import ConfigValue, value_hash
from vcenter_event_assistant.collectors.inventory import (
    InventoryObjectData,
    InventoryObservation,
)
from vcenter_event_assistant.collectors.inventory_config import (
    ConfigBaseline,
    ConfigObservation,
    select_vm_details,
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


def mock_inventory_config(
    now: datetime,
    *,
    observation: InventoryObservation,
    vcenter_name: str = "",
    baselines: dict[str, ConfigBaseline] | None = None,
) -> ConfigObservation:
    """関係のモックと同じ対象の構成を返す。"""
    started_at = utcnow()
    result = ConfigObservation(
        observation.instance_uuid, started_at, started_at, "configurationEx"
    )
    screenshot = vcenter_name == SCREENSHOT_VCENTER_NAME
    slot = int(now.timestamp()) // MOCK_INVENTORY_SLOT_SECONDS
    vm_values: dict[str, ConfigValue] = {}
    for moid, obj in observation.objects.items():
        match obj.entity_type:
            case "HostSystem":
                result.values[moid, "host_build"] = {
                    "version": "8.0.2",
                    "build": "21997540",
                }
                result.values[moid, "host_vswitch"] = {
                    "vSwitch0": {
                        "mtu": 1500,
                        "uplinks": ["vmnic0", "vmnic1"],
                        "teaming_policy": "loadbalance_srcid",
                        "active_nics": ["vmnic0"],
                        "standby_nics": ["vmnic1"],
                        "allow_promiscuous": False,
                        "mac_changes": False,
                        "forged_transmits": False,
                    }
                }
                result.values[moid, "host_portgroup"] = {
                    "VM Network": {
                        "vlan_id": 20
                        if screenshot and moid == SCREENSHOT_HOSTS[0][0]
                        else 0,
                        "vswitch": "vSwitch0",
                        "teaming_policy": None,
                        "active_nics": None,
                        "standby_nics": None,
                        "allow_promiscuous": None,
                        "mac_changes": None,
                        "forged_transmits": None,
                    }
                }
            case "ClusterComputeResource":
                result.values[moid, "cluster_ha"] = {
                    "enabled": True,
                    "host_monitoring": "enabled",
                    "vm_monitoring": None,
                    "admission_control_enabled": False,
                    "admission_control_policy": None,
                    "failover_level": None,
                    "auto_compute": None,
                    "cpu_failover_percent": None,
                    "memory_failover_percent": None,
                    "failover_hosts": None,
                    "restart_priority": "medium",
                    "isolation_response": None,
                }
                result.values[moid, "cluster_drs"] = {
                    "enabled": True,
                    "default_vm_behavior": "fullyAutomated",
                    "vmotion_rate": 3,
                }
            case "VirtualMachine":
                demo_vm = screenshot and moid == SCREENSHOT_VMS[0][0]
                changing = moid == _VMS[0][0]
                vm_values[moid] = {
                    "num_cpu": 4 if demo_vm or (changing and slot % 2 == 1) else 2,
                    "cores_per_socket": 1,
                    "memory_mb": 8192 if demo_vm else 4096,
                    "hardware_version": "vmx-21",
                    "guest_id": "otherGuest64",
                    "cpu_reservation_mhz": 0,
                    "cpu_limit_mhz": -1,
                    "cpu_shares": "normal",
                    "memory_reservation_mb": 0,
                    "memory_limit_mb": -1,
                    "memory_shares": "normal",
                    "devices": {},
                }
            case _:
                continue
        result.objects[moid] = obj

    result.change_versions = {
        moid: value_hash(value) for moid, value in vm_values.items()
    }
    selected = select_vm_details(result.change_versions, baselines or {})
    result.values.update({(moid, "vm_config"): vm_values[moid] for moid in selected})
    result.unchanged_vms = vm_values.keys() - set(selected)
    result.observed_at = utcnow()
    return result
