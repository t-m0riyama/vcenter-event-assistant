"""構成の概要と、変更の可能性がある VM の詳細を読み取る。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from time import monotonic
from typing import Any
from uuid import UUID

from pyVmomi import vim, vmodl

from vcenter_event_assistant.auth.timeutil import as_utc, utcnow
from vcenter_event_assistant.collectors.config_values import (
    FORMATS,
    VM_DETAIL_PATHS,
    VM_REQUIRED_DETAIL_PATHS,
    ConfigValue,
    DiskBackingUnreadable,
    normalize_build,
    normalize_drs,
    normalize_ha,
    normalize_host_network,
    normalize_vm,
)
from vcenter_event_assistant.collectors.inventory import InventoryObjectData

_PC = vmodl.query.PropertyCollector
_CONNECTION = "runtime.connectionState"
_TEMPLATE = "summary.config.template"
_VERSION = "config.changeVersion"
_HOST_PATHS = {
    "host_build": "summary.config.product",
    "host_vswitch": "config.network.vswitch",
    "host_portgroup": "config.network.portgroup",
}
VM_BATCH_SIZE = 200
VM_BATCH_RETRIES = 10
_CLUSTER_PATHS_LOCK = Lock()
_LEGACY_CLUSTER_PATHS: set[UUID] = set()


class ConfigReadTimeout(TimeoutError):
    """構成の読み取りの締め切りを過ぎた。"""


@dataclass(frozen=True, slots=True)
class ConfigBaseline:
    change_version: str | None
    format: int
    verified_at: datetime


@dataclass(slots=True)
class ConfigObservation:
    instance_uuid: str
    started_at: datetime
    observed_at: datetime
    cluster_path: str
    objects: dict[str, InventoryObjectData] = field(default_factory=dict)
    values: dict[tuple[str, str], ConfigValue] = field(default_factory=dict)
    change_versions: dict[str, str] = field(default_factory=dict)
    unchanged_vms: set[str] = field(default_factory=set)
    carry_over: set[tuple[str, str]] = field(default_factory=set)
    unread_vms: set[str] = field(default_factory=set)
    removed_vms: set[str] = field(default_factory=set)
    deferred_vms: set[str] = field(default_factory=set)
    duplicate_categories: set[str] = field(default_factory=set)


@dataclass(slots=True)
class PropertyRow:
    ref: Any
    props: dict[str, Any]
    missing: set[str]

    def get(self, path: str) -> Any:
        if path not in self.missing:
            return self.props.get(path)
        return None


@dataclass(slots=True)
class VMDetails:
    rows: dict[str, PropertyRow] = field(default_factory=dict)
    removed: set[str] = field(default_factory=set)
    deferred: set[str] = field(default_factory=set)


def overview_paths(cluster_path: str) -> dict[Any, tuple[str, ...]]:
    return {
        vim.HostSystem: ("name", _CONNECTION, *_HOST_PATHS.values()),
        vim.ClusterComputeResource: (
            "name",
            f"{cluster_path}.dasConfig",
            f"{cluster_path}.drsConfig",
        ),
        vim.VirtualMachine: ("name", _CONNECTION, _TEMPLATE, _VERSION),
    }


def _retrieve(
    collector: Any, spec: Any, before_page: Callable[[], None]
) -> list[PropertyRow]:
    token = None
    rows: list[PropertyRow] = []
    try:
        before_page()
        page = collector.RetrievePropertiesEx(
            specSet=[spec], options=_PC.RetrieveOptions(maxObjects=1000)
        )
        while page is not None:
            token = page.token
            rows.extend(
                PropertyRow(
                    row.obj,
                    {prop.name: prop.val for prop in row.propSet},
                    {prop.path for prop in row.missingSet},
                )
                for row in page.objects
            )
            if not token:
                break
            before_page()
            page = collector.ContinueRetrievePropertiesEx(token)
    except BaseException:
        if token:
            with suppress(Exception):
                collector.CancelRetrievePropertiesEx(token)
        raise
    return rows


def read_overview(
    content: Any, paths: dict[Any, tuple[str, ...]], *, deadline: float
) -> tuple[list[PropertyRow], datetime]:
    view = content.viewManager.CreateContainerView(
        content.rootFolder, list(paths), True
    )
    try:
        spec = _PC.FilterSpec(
            objectSet=[
                _PC.ObjectSpec(
                    obj=view,
                    skip=True,
                    selectSet=[
                        _PC.TraversalSpec(
                            type=vim.view.ContainerView, path="view", skip=False
                        )
                    ],
                )
            ],
            propSet=[
                # pyVmomi は list でない配列を 1 つの値として直列化し、要求が送れない。
                _PC.PropertySpec(type=kind, pathSet=list(attrs))
                for kind, attrs in paths.items()
            ],
        )

        def check_deadline() -> None:
            if monotonic() >= deadline:
                raise ConfigReadTimeout

        started_at = utcnow()
        rows = _retrieve(content.propertyCollector, spec, check_deadline)
    except BaseException:
        with suppress(Exception):
            view.Destroy()
        raise
    view.Destroy()
    return rows, started_at


def read_vm_details(content: Any, refs: list[Any], *, deadline: float) -> VMDetails:
    result = VMDetails()
    props = _PC.PropertySpec(type=vim.VirtualMachine, pathSet=list(VM_DETAIL_PATHS))
    for index in range(0, len(refs), VM_BATCH_SIZE):
        batch = {ref._moId: ref for ref in refs[index : index + VM_BATCH_SIZE]}
        retries = 0
        while batch:
            if monotonic() >= deadline:
                result.deferred.update(batch)
                result.deferred.update(
                    ref._moId for ref in refs[index + VM_BATCH_SIZE :]
                )
                return result
            spec = _PC.FilterSpec(
                objectSet=[
                    _PC.ObjectSpec(obj=ref, skip=False) for ref in batch.values()
                ],
                propSet=[props],
            )
            try:
                rows = _retrieve(content.propertyCollector, spec, lambda: None)
            except vmodl.fault.ManagedObjectNotFound as exc:
                moid = getattr(exc.obj, "_moId", None)
                if moid not in batch or retries >= VM_BATCH_RETRIES:
                    raise
                result.removed.add(moid)
                del batch[moid]
                retries += 1
            else:
                result.rows.update((row.ref._moId, row) for row in rows)
                break
    return result


def select_vm_details(
    versions: dict[str, str], baselines: dict[str, ConfigBaseline]
) -> list[str]:
    """版違い、値の変更、新規の順に読み、同じ群では古い観測を優先する。"""

    def priority(moid: str) -> tuple[int, datetime, str]:
        old = baselines.get(moid)
        if old is None:
            return 2, datetime.min, moid
        return int(old.format == FORMATS["vm_config"]), as_utc(old.verified_at), moid

    return sorted(
        (
            moid
            for moid, version in versions.items()
            if (old := baselines.get(moid)) is None
            or old.format != FORMATS["vm_config"]
            or old.change_version != version
        ),
        key=priority,
    )


def normalize_overview(
    rows: Iterable[PropertyRow], observation: ConfigObservation
) -> dict[str, Any]:
    """段 1 を正規化し、詳細を読める VM の参照を返す。"""
    refs = {}
    for row in rows:
        moid, kind = row.ref._moId, row.ref._wsdlName
        if kind == "VirtualMachine" and row.get(_TEMPLATE):
            continue
        observation.objects[moid] = InventoryObjectData(kind, row.get("name"))
        if kind == "VirtualMachine":
            version = row.get(_VERSION)
            if row.get(_CONNECTION) == "connected" and version is not None:
                observation.change_versions[moid] = str(version)
                refs[moid] = row.ref
            else:
                observation.carry_over.add((moid, "vm_config"))
            continue

        paths = (
            _HOST_PATHS
            if kind == "HostSystem"
            else {
                "cluster_ha": f"{observation.cluster_path}.dasConfig",
                "cluster_drs": f"{observation.cluster_path}.drsConfig",
            }
        )
        for category, path in paths.items():
            value = row.get(path)
            key = moid, category
            if value is None or (
                kind == "HostSystem" and row.get(_CONNECTION) != "connected"
            ):
                observation.carry_over.add(key)
                continue
            match category:
                case "host_build":
                    normalized = normalize_build(value)
                case "cluster_ha":
                    normalized = normalize_ha(value)
                case "cluster_drs":
                    normalized = normalize_drs(value)
                case _:
                    normalized, duplicate = normalize_host_network(
                        value, switches=category == "host_vswitch"
                    )
                    if duplicate:
                        observation.duplicate_categories.add(category)
            observation.values[key] = normalized
    return refs


def normalize_details(
    observation: ConfigObservation, selected: Iterable[str], details: VMDetails
) -> None:
    observation.deferred_vms = details.deferred
    observation.removed_vms = details.removed
    for moid in selected:
        if moid in details.deferred:
            continue
        row = details.rows.get(moid)
        if (
            row is not None
            and not row.missing
            and all(
                row.props.get(path) is not None for path in VM_REQUIRED_DETAIL_PATHS
            )
        ):
            try:
                observation.values[moid, "vm_config"] = normalize_vm(row.props)
            except DiskBackingUnreadable:
                pass
            else:
                observation.change_versions[moid] = str(row.props[_VERSION])
                continue
        observation.unread_vms.add(moid)
        observation.carry_over.add((moid, "vm_config"))


def read_inventory_config(
    content: Any,
    vcenter_id: UUID,
    baselines: dict[str, ConfigBaseline],
    *,
    deadline: float,
) -> ConfigObservation:
    """現在の構成を読み、持ち越しと読み残しを区別して返す。"""
    with _CLUSTER_PATHS_LOCK:
        legacy = vcenter_id in _LEGACY_CLUSTER_PATHS
    cluster_path = "configuration" if legacy else "configurationEx"
    try:
        rows, started_at = read_overview(
            content, overview_paths(cluster_path), deadline=deadline
        )
    except vmodl.query.InvalidProperty:
        if legacy:
            raise
        cluster_path = "configuration"
        rows, started_at = read_overview(
            content, overview_paths(cluster_path), deadline=deadline
        )
        with _CLUSTER_PATHS_LOCK:
            _LEGACY_CLUSTER_PATHS.add(vcenter_id)

    observation = ConfigObservation(
        content.about.instanceUuid or "", started_at, started_at, cluster_path
    )
    refs = normalize_overview(rows, observation)
    selected = select_vm_details(observation.change_versions, baselines)
    observation.unchanged_vms = refs.keys() - set(selected)
    details = read_vm_details(
        content, [refs[moid] for moid in selected], deadline=deadline
    )
    observation.observed_at = utcnow()
    normalize_details(observation, selected, details)
    return observation
