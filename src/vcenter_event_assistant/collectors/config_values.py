"""vSphere の属性から比較する構成だけを取り出す。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

type Value = str | int | float | bool | None | list[Value] | dict[str, Value]
type ConfigValue = dict[str, Value]

FORMATS = dict.fromkeys(
    (
        "host_build",
        "host_vswitch",
        "host_portgroup",
        "cluster_ha",
        "cluster_drs",
        "vm_config",
    ),
    1,
)
MAX_DIFF_VALUE_LENGTH = 1024


def encode(value: Value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def value_hash(value: ConfigValue) -> str:
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def _scalar(value: Any) -> Value:
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, str):
        return str(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise TypeError("比較する構成に未対応の値が含まれています。")


def _fields(obj: object, **fields: str) -> ConfigValue:
    return {key: _scalar(getattr(obj, attr, None)) for key, attr in fields.items()}


def _type_name(obj: object) -> str:
    return type(obj).__name__.rsplit(".", 1)[-1]


def normalize_build(product: object) -> ConfigValue:
    return _fields(product, version="version", build="build")


def _network_policy(spec: object) -> ConfigValue:
    policy = getattr(spec, "policy", None)
    teaming = getattr(policy, "nicTeaming", None)
    order = getattr(teaming, "nicOrder", None)
    security = getattr(policy, "security", None)
    active = getattr(order, "activeNic", None)
    standby = getattr(order, "standbyNic", None)
    return {
        **_fields(teaming, teaming_policy="policy"),
        "active_nics": [_scalar(nic) for nic in active] if active is not None else None,
        "standby_nics": [_scalar(nic) for nic in standby]
        if standby is not None
        else None,
        **_fields(
            security,
            allow_promiscuous="allowPromiscuous",
            mac_changes="macChanges",
            forged_transmits="forgedTransmits",
        ),
    }


def normalize_host_network(
    entries: Iterable[Any], *, switches: bool
) -> tuple[ConfigValue, bool]:
    """同名の要素は最初の値を残し、呼び出し元に重複を知らせる。"""
    result: ConfigValue = {}
    duplicate = False
    for entry in entries:
        spec = getattr(entry, "spec", None)
        name = getattr(entry if switches else spec, "name", None)
        if name is None:
            continue
        if name in result:
            duplicate = True
            continue
        fields: ConfigValue
        if switches:
            uplinks: list[Value] = sorted(
                str(nic).removeprefix("key-vim.host.PhysicalNic-")
                for nic in getattr(entry, "pnic", ()) or ()
            )
            fields = {
                **_fields(entry, mtu="mtu"),
                "uplinks": uplinks,
            }
        else:
            fields = _fields(spec, vlan_id="vlanId", vswitch="vswitchName")
        result[str(name)] = {**fields, **_network_policy(spec)}
    return result, duplicate


def normalize_ha(ha: object) -> ConfigValue:
    policy = getattr(ha, "admissionControlPolicy", None)
    policy_name = (
        _type_name(policy)
        .removeprefix("Failover")
        .removesuffix("AdmissionControlPolicy")
        if policy is not None
        else None
    )
    auto_compute = (
        getattr(policy, "autoComputePercentages", None)
        if policy_name == "Resources"
        else None
    )
    percentages = policy if auto_compute is False else None
    failover_hosts: list[Value] | None = None
    if policy_name == "Host":
        failover_hosts = sorted(
            str(moid)
            for host in getattr(policy, "failoverHosts", ()) or ()
            if (moid := getattr(host, "_moId", None)) is not None
        )
    return {
        **_fields(
            ha,
            enabled="enabled",
            host_monitoring="hostMonitoring",
            vm_monitoring="vmMonitoring",
            admission_control_enabled="admissionControlEnabled",
        ),
        "admission_control_policy": policy_name,
        **_fields(policy, failover_level="failoverLevel"),
        "auto_compute": auto_compute,
        **_fields(
            percentages,
            cpu_failover_percent="cpuFailoverResourcesPercent",
            memory_failover_percent="memoryFailoverResourcesPercent",
        ),
        "failover_hosts": failover_hosts,
        **_fields(
            getattr(ha, "defaultVmSettings", None),
            restart_priority="restartPriority",
            isolation_response="isolationResponse",
        ),
    }


def normalize_drs(drs: object) -> ConfigValue:
    return _fields(
        drs,
        enabled="enabled",
        default_vm_behavior="defaultVmBehavior",
        vmotion_rate="vmotionRate",
    )


def _shares(allocation: object) -> Value:
    shares = getattr(allocation, "shares", None)
    level = _scalar(getattr(shares, "level", None))
    if level == "custom":
        return f"custom:{getattr(shares, 'shares', None)}"
    return level


def _nic_network(backing: object) -> Value:
    for backing_class in type(backing).__mro__:
        match backing_class.__name__.rsplit(".", 1)[-1]:
            case "NetworkBackingInfo":
                return _scalar(getattr(backing, "deviceName", None))
            case "DistributedVirtualPortBackingInfo":
                return _scalar(
                    getattr(getattr(backing, "port", None), "portgroupKey", None)
                )
            case "OpaqueNetworkBackingInfo":
                return _scalar(getattr(backing, "opaqueNetworkId", None))
    return None


_MAX_DISK_PARENT_DEPTH = 64


def disk_backing_root(backing: object) -> object:
    """元のディスクを特定できないときは None を返す。"""
    seen: set[int] = set()
    for _ in range(_MAX_DISK_PARENT_DEPTH + 1):
        identity = id(backing)
        if identity in seen:
            break
        seen.add(identity)
        try:
            parent = getattr(backing, "parent", None)
        except Exception:
            # 不完全な backing から差分ディスクの値を採用しない。
            return None
        if parent is None:
            return backing
        backing = parent
    return None


def normalize_disk_uuid(value: object) -> str | None:
    """ディスクの UUID を比べる形にする。前後の空白を除いて小文字にし、空なら None にする。"""
    if not isinstance(value, str):
        return None
    return value.strip().lower() or None


class DiskBackingUnreadable(Exception):
    """元のディスクの backing を特定できなかった。"""


def _devices(devices: Iterable[Any]) -> ConfigValue:
    result: ConfigValue = {}
    for device in devices:
        base_names = {cls.__name__.rsplit(".", 1)[-1] for cls in type(device).__mro__}
        backing = getattr(device, "backing", None)
        if "VirtualDisk" in base_names:
            prefix = "disk"
            backing = disk_backing_root(backing)
            if backing is None:
                raise DiskBackingUnreadable
            fields = {
                **_fields(device, capacity_kb="capacityInKB"),
                **_fields(backing, thin="thinProvisioned", disk_mode="diskMode"),
                "uuid": normalize_disk_uuid(getattr(backing, "uuid", None)),
            }
        elif "VirtualEthernetCard" in base_names:
            prefix = "nic"
            fields = {
                "adapter": _type_name(device),
                "network": _nic_network(backing),
                **_fields(
                    getattr(device, "connectable", None),
                    start_connected="startConnected",
                ),
                **_fields(device, mac_address="macAddress"),
            }
        else:
            continue
        key = getattr(device, "key", None)
        if key is not None:
            result[f"{prefix}:{key}"] = {
                **_fields(getattr(device, "deviceInfo", None), label="label"),
                **fields,
            }
    return result


VM_DETAIL_PATHS = (
    "config.changeVersion",
    "config.hardware.numCPU",
    "config.hardware.numCoresPerSocket",
    "config.hardware.memoryMB",
    "config.version",
    "config.guestId",
    "config.cpuAllocation",
    "config.memoryAllocation",
    "config.hardware.device",
)


VM_REQUIRED_DETAIL_PATHS = (
    "config.changeVersion",
    "config.hardware.numCPU",
    "config.hardware.memoryMB",
    "config.hardware.device",
)


def normalize_vm(props: Mapping[str, Any]) -> ConfigValue:
    cpu, memory = (
        props.get("config.cpuAllocation"),
        props.get("config.memoryAllocation"),
    )
    return {
        "num_cpu": _scalar(props["config.hardware.numCPU"]),
        "cores_per_socket": _scalar(props.get("config.hardware.numCoresPerSocket")),
        "memory_mb": _scalar(props["config.hardware.memoryMB"]),
        "hardware_version": _scalar(props.get("config.version")),
        "guest_id": _scalar(props.get("config.guestId")),
        **_fields(cpu, cpu_reservation_mhz="reservation", cpu_limit_mhz="limit"),
        **_fields(memory, memory_reservation_mb="reservation", memory_limit_mb="limit"),
        "cpu_shares": _shares(cpu),
        "memory_shares": _shares(memory),
        "devices": _devices(props["config.hardware.device"]),
    }


@dataclass(frozen=True, slots=True)
class ConfigDiff:
    element: str | None
    element_label: str | None
    attribute: str | None
    old_value: str | None
    new_value: str | None
    truncated: bool


def _diff(
    element: str | None,
    label: str | None,
    attribute: str | None,
    old: str | None,
    new: str | None,
) -> ConfigDiff:
    truncated = any(
        len(text) > MAX_DIFF_VALUE_LENGTH for text in (old, new) if text is not None
    )
    return ConfigDiff(
        element,
        label,
        attribute,
        old[:MAX_DIFF_VALUE_LENGTH] if old is not None else None,
        new[:MAX_DIFF_VALUE_LENGTH] if new is not None else None,
        truncated,
    )


def diff_config(
    category: str, old: ConfigValue, new: ConfigValue
) -> Iterable[ConfigDiff]:
    """項目の変更と要素の増減を、差分の行にする。"""
    if category in {"host_vswitch", "host_portgroup"}:
        old_elements, new_elements = old, new
    else:
        excluded = {"devices"} if category == "vm_config" else set()
        for key in sorted((old.keys() | new.keys()) - excluded):
            before, after = encode(old.get(key)), encode(new.get(key))
            if before != after:
                yield _diff(None, None, key, before, after)
        if category != "vm_config":
            return
        old_elements, new_elements = old["devices"], new["devices"]

    for element in sorted(old_elements.keys() | new_elements.keys()):
        before, after = old_elements.get(element), new_elements.get(element)
        if (
            category == "vm_config"
            and element.startswith("disk:")
            and before is not None
            and after is not None
            and (old_uuid := before.get("uuid")) is not None
            and (new_uuid := after.get("uuid")) is not None
            and old_uuid != new_uuid
        ):
            yield _diff(element, before.get("label"), None, encode(before), None)
            yield _diff(element, after.get("label"), None, None, encode(after))
            continue
        label = element
        if category == "vm_config":
            label = (after if after is not None else before).get("label")
        if before is None or after is None:
            yield _diff(
                element,
                label,
                None,
                encode(before) if before is not None else None,
                encode(after) if after is not None else None,
            )
        else:
            for key in sorted(before.keys() | after.keys()):
                old_text, new_text = encode(before.get(key)), encode(after.get(key))
                if old_text != new_text:
                    yield _diff(element, label, key, old_text, new_text)
