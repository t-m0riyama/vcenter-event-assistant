"""PropertyCollector から管理対象と関係をまとめて読み取る。"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass

from pyVmomi import vim, vmodl

Relation = tuple[str, str, str]

_NETWORK_TYPES = frozenset({"Network", "DistributedVirtualPortgroup", "OpaqueNetwork"})
_RELATION_PROPERTIES = {
    "VirtualMachine": (
        ("runtime.host", "vm_host", {"HostSystem"}, False),
        ("datastore", "vm_datastore", {"Datastore"}, True),
        ("network", "vm_network", _NETWORK_TYPES, True),
    ),
    "HostSystem": (
        ("parent", "host_cluster", {"ClusterComputeResource"}, False),
        ("datastore", "host_datastore", {"Datastore"}, True),
        ("network", "host_network", _NETWORK_TYPES, True),
    ),
}
_PROPERTIES = {
    vim.VirtualMachine: (
        "name",
        "runtime.host",
        "runtime.connectionState",
        "datastore",
        "network",
        "summary.config.template",
    ),
    vim.HostSystem: (
        "name",
        "parent",
        "datastore",
        "network",
        "runtime.connectionState",
    ),
    vim.ClusterComputeResource: ("name",),
    vim.Datastore: ("name",),
    vim.Network: ("name",),
}


@dataclass(frozen=True, slots=True)
class InventoryObjectData:
    entity_type: str
    name: str | None


@dataclass(frozen=True, slots=True)
class InventoryObservation:
    instance_uuid: str
    objects: dict[str, InventoryObjectData]
    relations: set[Relation]
    carry_over: set[tuple[str, str]]


def read_inventory(content: vim.ServiceInstanceContent) -> InventoryObservation:
    """接続済み vCenter の管理対象と関係を読む。各参照からは種別と moid だけを取る。"""
    pc = vmodl.query.PropertyCollector
    collector = content.propertyCollector
    instance_uuid = content.about.instanceUuid or ""
    objects: dict[str, InventoryObjectData] = {}
    relations: set[Relation] = set()
    carry_over: set[tuple[str, str]] = set()
    view = content.viewManager.CreateContainerView(
        content.rootFolder, list(_PROPERTIES), True
    )
    token = None
    failed = False
    try:
        spec = pc.FilterSpec(
            objectSet=[
                pc.ObjectSpec(
                    obj=view,
                    skip=True,
                    selectSet=[
                        pc.TraversalSpec(
                            type=vim.view.ContainerView, path="view", skip=False
                        )
                    ],
                )
            ],
            propSet=[
                # pyVmomi は list でない配列を 1 つの値として直列化し、要求が送れない。
                pc.PropertySpec(type=kind, pathSet=list(paths))
                for kind, paths in _PROPERTIES.items()
            ],
        )
        page = collector.RetrievePropertiesEx(
            specSet=[spec], options=pc.RetrieveOptions(maxObjects=1000)
        )
        while page is not None:
            token = page.token
            for row in page.objects:
                moid, entity_type = row.obj._moId, row.obj._wsdlName
                props = {prop.name: prop.val for prop in row.propSet}
                if entity_type == "VirtualMachine" and props.get(
                    "summary.config.template"
                ):
                    continue
                missing = {prop.path for prop in row.missingSet}
                name = None if "name" in missing else props.get("name")
                objects[moid] = InventoryObjectData(entity_type, name)
                disconnected = props.get("runtime.connectionState") != "connected"
                for path, kind, parent_types, many in _RELATION_PROPERTIES.get(
                    entity_type, ()
                ):
                    if path in missing or (many and disconnected):
                        carry_over.add((kind, moid))
                        continue
                    value = props.get(path)
                    if value is None:
                        continue
                    for ref in value if many else (value,):
                        if ref._wsdlName in parent_types:
                            relations.add((kind, moid, ref._moId))
            if not token:
                break
            page = collector.ContinueRetrievePropertiesEx(token)
    except BaseException:
        failed = True
        if token:
            with suppress(Exception):
                collector.CancelRetrievePropertiesEx(token)
        raise
    finally:
        try:
            view.Destroy()
        except Exception:
            # 読み取りの例外を後片付けの例外で上書きしない。
            if not failed:
                raise
    visible_relations = {
        edge for edge in relations if edge[1] in objects and edge[2] in objects
    }
    return InventoryObservation(instance_uuid, objects, visible_relations, carry_over)
