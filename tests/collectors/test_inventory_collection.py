"""PropertyCollector の応答からインベントリを組み立てる試験。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pyVmomi import vim, vmodl

from vcenter_event_assistant.collectors.inventory import read_inventory

pc = vmodl.query.PropertyCollector


def row(ref, *, missing=(), **props):
    return pc.ObjectContent(
        obj=ref,
        propSet=[
            vmodl.DynamicProperty(name=key, val=value) for key, value in props.items()
        ],
        missingSet=[
            pc.MissingProperty(path=path, fault=vim.fault.NoPermission())
            for path in missing
        ],
    )


def content_for(*pages):
    view = Mock(spec=vim.view.ContainerView("view-1"))
    view._GetMoId.return_value = "view-1"
    collector = Mock()
    collector.RetrievePropertiesEx.return_value = pages[0]
    collector.ContinueRetrievePropertiesEx.side_effect = pages[1:]
    root = vim.Folder("root-1")
    content = SimpleNamespace(
        about=SimpleNamespace(instanceUuid="vc-1"),
        rootFolder=root,
        viewManager=SimpleNamespace(CreateContainerView=Mock(return_value=view)),
        propertyCollector=collector,
    )
    return content, view, collector


def test_inventory_pages_types_and_missing_properties():
    stub = Mock()
    stub.InvokeAccessor.side_effect = AssertionError("参照のリモート属性を読んだ")
    host = vim.HostSystem("host-1", stub)
    standalone = vim.HostSystem("host-2", stub)
    cluster = vim.ClusterComputeResource("domain-c1", stub)
    ds = vim.Datastore("datastore-1", stub)
    portgroup = vim.dvs.DistributedVirtualPortgroup("dvportgroup-1", stub)
    opaque = vim.OpaqueNetwork("opaque-1", stub)
    vm = vim.VirtualMachine("vm-1", stub)
    content, view, collector = content_for(
        pc.RetrieveResult(
            token="next",
            objects=[
                row(
                    host,
                    name="esx%2f01",
                    parent=cluster,
                    datastore=vim.Datastore.Array([ds]),
                    network=vim.Network.Array([portgroup]),
                    **{"runtime.connectionState": "connected"},
                ),
                row(
                    standalone,
                    name="esx02",
                    parent=vim.ComputeResource("domain-s1", stub),
                    datastore=vim.Datastore.Array([ds]),
                    network=vim.Network.Array(),
                    **{"runtime.connectionState": "disconnected"},
                ),
                row(
                    vm,
                    name="vm",
                    missing=("datastore", "name"),
                    network=vim.Network.Array(),
                    **{"runtime.host": host, "runtime.connectionState": "connected"},
                ),
                row(
                    vim.VirtualMachine("template-1", stub),
                    name="template",
                    **{"summary.config.template": True, "runtime.host": host},
                ),
                row(
                    vim.VirtualMachine("vm-2", stub),
                    name="vm2",
                    **{"runtime.host": host, "runtime.connectionState": "inaccessible"},
                ),
                row(
                    vim.HostSystem("host-3", stub),
                    name="esx03",
                    datastore=vim.Datastore.Array([vim.Datastore("hidden", stub)]),
                    network=vim.Network.Array([opaque]),
                    **{"runtime.connectionState": "connected"},
                ),
            ],
        ),
        pc.RetrieveResult(
            objects=[
                row(cluster, name="cluster"),
                row(ds, name="ds"),
                row(portgroup, name="dpg"),
                row(opaque, name="opaque"),
            ]
        ),
    )
    result = read_inventory(content)
    assert result.instance_uuid == "vc-1"
    assert set(result.objects) == {
        "host-1",
        "host-2",
        "host-3",
        "domain-c1",
        "datastore-1",
        "dvportgroup-1",
        "opaque-1",
        "vm-1",
        "vm-2",
    }
    assert result.objects["host-1"].name == "esx%2f01"
    assert result.objects["vm-1"].name is None
    assert result.objects["dvportgroup-1"].entity_type == "DistributedVirtualPortgroup"
    assert result.objects["opaque-1"].entity_type == "OpaqueNetwork"
    assert result.relations == {
        ("host_cluster", "host-1", "domain-c1"),
        ("host_datastore", "host-1", "datastore-1"),
        ("host_network", "host-1", "dvportgroup-1"),
        ("host_network", "host-3", "opaque-1"),
        ("vm_host", "vm-1", "host-1"),
        ("vm_host", "vm-2", "host-1"),
    }
    assert result.carry_over == {
        ("vm_datastore", "vm-1"),
        ("vm_datastore", "vm-2"),
        ("vm_network", "vm-2"),
        ("host_datastore", "host-2"),
        ("host_network", "host-2"),
    }
    args = content.viewManager.CreateContainerView.call_args.args
    assert args == (
        content.rootFolder,
        [
            vim.VirtualMachine,
            vim.HostSystem,
            vim.ClusterComputeResource,
            vim.Datastore,
            vim.Network,
        ],
        True,
    )
    request = collector.RetrievePropertiesEx.call_args
    assert request.kwargs["options"].maxObjects == 1000
    obj = request.kwargs["specSet"][0].objectSet[0]
    assert obj.skip and obj.selectSet[0].path == "view" and not obj.selectSet[0].skip
    stub.InvokeAccessor.assert_not_called()
    collector.ContinueRetrievePropertiesEx.assert_called_once_with("next")
    collector.CancelRetrievePropertiesEx.assert_not_called()
    view.Destroy.assert_called_once_with()


def test_inventory_cancels_token_and_destroys_view_after_failure():
    content, view, collector = content_for(pc.RetrieveResult(token="next"))
    collector.ContinueRetrievePropertiesEx.side_effect = RuntimeError("response failed")
    collector.CancelRetrievePropertiesEx.side_effect = RuntimeError("cancel failed")
    with pytest.raises(RuntimeError, match="response failed"):
        read_inventory(content)
    collector.CancelRetrievePropertiesEx.assert_called_once_with("next")
    view.Destroy.assert_called_once_with()
