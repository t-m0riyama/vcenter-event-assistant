"""実機の確認の出力と、読み取り専用の登録情報の取得を試験する。"""

from unittest.mock import Mock

import pytest
from pyVmomi import vim, vmodl
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from scripts import probe_inventory_config as probe
from vcenter_event_assistant.collectors.config_values import VM_DETAIL_PATHS
from vcenter_event_assistant.collectors.inventory_config import PropertyRow, VMDetails
from vcenter_event_assistant.db.base import Base
from vcenter_event_assistant.db.models import VCenter
from vcenter_event_assistant.settings import Settings
from vcenter_event_assistant.settings_binding import require_settings


def test_probe_reports_paths_aggregate_changes_and_no_object_details(
    monkeypatch, capsys
):
    host = vim.HostSystem("secret-host-id")
    cluster = vim.ClusterComputeResource("secret-cluster-id")
    vm = vim.VirtualMachine("secret-vm-id")
    disconnected = vim.VirtualMachine("secret-disconnected-id")
    center = VCenter(
        host="secret-host.example",
        username="secret-user",
        password="secret-password",
        protocol="https",
        port=443,
        verify_ssl=True,
    )
    content, connection = object(), Mock()
    connection.RetrieveContent.return_value = content
    connect = Mock(return_value=connection)
    disconnect = Mock()
    pause = Mock()
    find = Mock(return_value=center)
    settings = require_settings()

    async def lookup(name, app_settings):
        return find(name, app_settings)

    monkeypatch.setattr(probe, "connect_vcenter", connect)
    monkeypatch.setattr(probe, "disconnect", disconnect)
    monkeypatch.setattr(probe, "sleep", pause)
    monkeypatch.setattr(probe, "_find_vcenter", lookup)
    monkeypatch.setattr(probe, "get_settings", lambda: settings)
    samples = 0
    checked = []

    def overview(target, paths, **kwargs):
        nonlocal samples
        assert target is content
        if len(paths) == 1:
            kind, attrs = next(iter(paths.items()))
            path = attrs[-1]
            assert attrs == (("name",) if path == "name" else ("name", path))
            checked.append(path)
            if path == "configurationEx.dasConfig":
                raise vmodl.query.InvalidProperty(name="secret-attribute")
            if path == "config.network.portgroup":
                return [
                    PropertyRow(host, {"name": "secret-empty", path: []}, set()),
                    PropertyRow(host, {"name": "secret-missing"}, {path}),
                    PropertyRow(host, {"name": "secret-absent"}, set()),
                ], probe.utcnow()
            refs = {
                vim.HostSystem: host,
                vim.ClusterComputeResource: cluster,
                vim.VirtualMachine: vm,
            }
            return [
                PropertyRow(refs[kind], {path: "secret-sample"}, set())
            ], probe.utcnow()
        samples += 1
        assert paths[vim.ClusterComputeResource] == (
            "name",
            "configuration.dasConfig",
            "configuration.drsConfig",
        )
        return [
            PropertyRow(
                host,
                {
                    "name": "secret-host-name",
                    "runtime.connectionState": "connected",
                    "config.network.vswitch": [
                        vim.host.VirtualSwitch(name="secret-switch", mtu=1500 * samples)
                    ],
                },
                set(),
            ),
            PropertyRow(
                vm,
                {
                    "name": "secret-vm-name",
                    "runtime.connectionState": "connected",
                    "config.changeVersion": f"secret-generation-{samples}",
                },
                set(),
            ),
            PropertyRow(
                disconnected, {"runtime.connectionState": "disconnected"}, set()
            ),
        ], probe.utcnow()

    def details(target, refs, **kwargs):
        assert target is content and refs == [vm, disconnected]
        root = vim.vm.device.VirtualDisk.FlatVer2BackingInfo(
            fileName="secret-base",
            uuid="secret-root-uuid",
            thinProvisioned=True,
            diskMode="persistent",
        )
        equivalent = vim.vm.device.VirtualDisk.FlatVer2BackingInfo(
            fileName="secret-equivalent",
            parent=root,
            uuid=" SECRET-ROOT-UUID ",
            thinProvisioned=True,
        )
        intermediate = vim.vm.device.VirtualDisk.FlatVer2BackingInfo(
            fileName="secret-intermediate", parent=root, thinProvisioned=False
        )
        delta = vim.vm.device.VirtualDisk.FlatVer2BackingInfo(
            fileName="secret-delta",
            parent=intermediate,
            uuid="secret-delta-uuid",
            thinProvisioned=False,
        )
        devices = [
            vim.vm.device.VirtualDisk(key=2000, backing=delta),
            vim.vm.device.VirtualDisk(key=2001, backing=equivalent),
            vim.vm.device.VirtualDisk(key=2002, backing=root),
            vim.vm.device.VirtualDisk(
                key=2003, backing=vim.vm.device.VirtualDisk.FlatVer1BackingInfo()
            ),
        ]
        props = dict(
            zip(
                VM_DETAIL_PATHS,
                (
                    f"secret-version-{samples}",
                    samples,
                    1,
                    4096,
                    "vmx-21",
                    "secret-guest",
                    vim.ResourceAllocationInfo(),
                    vim.ResourceAllocationInfo(),
                    devices,
                ),
                strict=True,
            )
        )
        return VMDetails(
            {vm._moId: PropertyRow(vm, props, set())}, {disconnected._moId}
        )

    monkeypatch.setattr(probe, "read_overview", overview)
    monkeypatch.setattr(probe, "read_vm_details", details)
    assert probe.main(["secret-vcenter-name"]) == 0
    find.assert_called_once_with("secret-vcenter-name", settings)
    pause.assert_called_once_with(300)
    disconnect.assert_called_once_with(connection)
    assert connect.call_args.kwargs["host"] == "secret-host.example"
    assert "configuration.dasConfig" in checked and "configuration.drsConfig" in checked

    captured = capsys.readouterr()
    assert "secret" not in captured.out + captured.err
    assert (
        "stage1 ClusterComputeResource configurationEx.dasConfig vmodl.query.InvalidProperty"
        in captured.out
    )
    assert (
        "stage1 ClusterComputeResource configuration.dasConfig ok propSet=1"
        in captured.out
    )
    assert (
        "config.network.portgroup ok propSet=1 missingSet=1 absent=1 empty_array=1"
        in captured.out
    )
    assert "stage1 HostSystem objects=1 bytes=" in captured.out
    assert "stage1 seconds=" in captured.out and "stage2 seconds=" in captured.out
    assert "requested=2" in captured.out and "ManagedObjectNotFound=1" in captured.out
    assert "stage2 VirtualMachine objects=1 bytes=" in captured.out
    assert "stage2 disks_with_parent=2 disks_with_different_thin=1" in captured.out
    assert (
        "stage2 disks_with_uuid=3 disks_without_root_uuid=1 disks_with_different_uuid=1"
        in captured.out
    )
    assert "changed host_vswitch mtu count=1" in captured.out
    assert "changed vm_config num_cpu count=1" in captured.out
    assert "changed config.changeVersion count=1" in captured.out

    pause.reset_mock()
    samples = 0
    assert probe.main(["secret-vcenter-name", "--interval-seconds", "0"]) == 0
    pause.assert_called_once_with(0)


def test_probe_prints_only_type_when_connection_fails(monkeypatch, capsys):
    async def lookup(*_):
        return VCenter(host="hidden", username="hidden", password="hidden")

    monkeypatch.setattr(probe, "_find_vcenter", lookup)
    monkeypatch.setattr(probe, "connect_vcenter", Mock(side_effect=OSError("hidden")))
    assert probe.main(["hidden"]) == 1
    assert capsys.readouterr().err == "OSError\n"


async def test_probe_uses_existing_sqlite_db_read_only_and_does_not_create_a_file(
    tmp_path,
):
    db_file = tmp_path / "existing db.sqlite"
    settings = Settings(database_url=f"sqlite+aiosqlite:///{db_file}")
    setup = create_async_engine(settings.database_url)
    try:
        async with setup.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(setup)() as session:
            session.add(
                VCenter(
                    name="target", host="vc.example", username="test", password="test"
                )
            )
            await session.commit()
    finally:
        await setup.dispose()

    center = await probe._find_vcenter("target", settings)
    assert center.host == "vc.example"
    assert await probe._find_vcenter("another", settings) is None
    readonly = create_async_engine(probe._read_only_settings(settings).database_url)
    try:
        async with readonly.begin() as conn:
            assert await conn.scalar(select(VCenter.name)) == "target"
            with pytest.raises(OperationalError, match="readonly"):
                await conn.execute(VCenter.__table__.delete())
    finally:
        await readonly.dispose()
    missing = tmp_path / "absent.sqlite"
    with pytest.raises(OperationalError):
        await probe._find_vcenter(
            "target", Settings(database_url=f"sqlite+aiosqlite:///{missing}")
        )
    assert not missing.exists()


def test_probe_uuid_counts_exclude_disks_without_a_resolved_root(capsys):
    ref = vim.VirtualMachine("private-moid")
    root = vim.vm.device.VirtualDisk.FlatVer2BackingInfo()
    delta = vim.vm.device.VirtualDisk.FlatVer2BackingInfo(
        parent=root, uuid="private-delta-uuid"
    )
    devices = [
        vim.vm.device.VirtualDisk(key=2000, backing=delta),
        vim.vm.device.VirtualDisk(key=2001),
    ]
    probe._report_disk_backings(
        [PropertyRow(ref, {"config.hardware.device": devices}, set())]
    )
    printed = capsys.readouterr().out
    assert (
        "disks_with_uuid=0 disks_without_root_uuid=1 disks_with_different_uuid=0"
        in printed
    )
    assert "private" not in printed
