"""タイムラインで検出する構成変更の定義。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConfigChangeDefinition:
    kind: str
    label: str
    event_types: tuple[str, ...]
    task_operations: tuple[str, ...]


CONFIG_CHANGE_DEFINITIONS = (
    ConfigChangeDefinition(
        kind="vm_reconfigure",
        label="VM の構成変更",
        event_types=("vim.event.VmReconfiguredEvent",),
        task_operations=("VirtualMachine.reconfigure",),
    ),
    ConfigChangeDefinition(
        kind="maintenance_enter",
        label="メンテナンスモードに入った",
        event_types=(
            "vim.event.EnteringMaintenanceModeEvent",
            "vim.event.EnteredMaintenanceModeEvent",
            "esx.audit.maintenancemode.entering",
            "esx.audit.maintenancemode.entered",
            "com.vmware.vc.sdrs.DatastoreEnteringMaintenanceModeEvent",
            "com.vmware.vc.sdrs.DatastoreEnteredMaintenanceModeEvent",
        ),
        task_operations=(
            "HostSystem.enterMaintenanceMode",
            "Datastore.enterMaintenanceMode",
        ),
    ),
    ConfigChangeDefinition(
        kind="maintenance_exit",
        label="メンテナンスモードを出た",
        event_types=(
            "vim.event.ExitMaintenanceModeEvent",
            "esx.audit.maintenancemode.exited",
            "com.vmware.vc.sdrs.DatastoreExitedMaintenanceModeEvent",
        ),
        task_operations=(
            "HostSystem.exitMaintenanceMode",
            "Datastore.exitMaintenanceMode",
        ),
    ),
    ConfigChangeDefinition(
        kind="cluster_config",
        label="クラスタの設定の変更",
        event_types=(
            "vim.event.ClusterReconfiguredEvent",
            "vim.event.DrsEnabledEvent",
            "vim.event.DrsDisabledEvent",
            "vim.event.DasEnabledEvent",
            "vim.event.DasDisabledEvent",
            "vim.event.DasAdmissionControlEnabledEvent",
            "vim.event.DasAdmissionControlDisabledEvent",
            "com.vmware.vc.sdrs.StorageDrsDisabledEvent",
        ),
        task_operations=(
            "ClusterComputeResource.reconfigureEx",
            "ClusterComputeResource.reconfigure",
            "ComputeResource.reconfigureEx",
        ),
    ),
    ConfigChangeDefinition(
        kind="network_config",
        label="ネットワークの設定の変更",
        event_types=(
            "vim.event.DvsReconfiguredEvent",
            "vim.event.DVPortgroupReconfiguredEvent",
            "vim.event.DvsPortReconfiguredEvent",
            "vim.event.DVPortgroupCreatedEvent",
            "vim.event.DVPortgroupDestroyedEvent",
        ),
        task_operations=(
            "DistributedVirtualSwitch.reconfigure",
            "DistributedVirtualSwitch.reconfigurePort",
            "DistributedVirtualSwitch.addPortgroup",
            "DistributedVirtualSwitch.addPortgroups",
            "dvs.VmwareDistributedVirtualSwitch.reconfigure",
            "dvs.VmwareDistributedVirtualSwitch.reconfigurePort",
            "dvs.VmwareDistributedVirtualSwitch.addPortgroup",
            "dvs.VmwareDistributedVirtualSwitch.addPortgroups",
            "dvs.DistributedVirtualPortgroup.reconfigure",
            "dvs.DistributedVirtualPortgroup.destroy",
            "host.NetworkSystem.updateNetworkConfig",
            "host.NetworkSystem.updateVirtualSwitch",
            "host.NetworkSystem.addVirtualSwitch",
            "host.NetworkSystem.removeVirtualSwitch",
            "host.NetworkSystem.updatePortGroup",
            "host.NetworkSystem.addPortGroup",
            "host.NetworkSystem.removePortGroup",
            "host.NetworkSystem.updateDnsConfig",
            "host.NetworkSystem.updateIpRouteConfig",
        ),
    ),
    ConfigChangeDefinition(
        kind="storage_config",
        label="ストレージの設定の変更",
        event_types=("vim.event.DatastoreIORMReconfiguredEvent",),
        task_operations=(
            "host.StorageSystem.setMultipathLunPolicy",
            "host.StorageSystem.mountVmfsVolume",
            "host.StorageSystem.unmountVmfsVolume",
        ),
    ),
    ConfigChangeDefinition(
        kind="resource_config",
        label="リソースの割り当ての変更",
        event_types=("vim.event.ResourcePoolReconfiguredEvent",),
        task_operations=(
            "ResourcePool.updateConfig",
            "ResourcePool.updateChildResourceConfiguration",
            "VirtualApp.updateConfig",
            "VirtualApp.updateChildResourceConfiguration",
        ),
    ),
    ConfigChangeDefinition(
        kind="host_config",
        label="ホストの設定の変更",
        event_types=(
            "vim.event.HostProfileAppliedEvent",
            "esx.audit.usb.config.changed",
        ),
        task_operations=(
            "profile.host.profileEngine.HostProfileManager.applyHostConfig",
            "option.OptionManager.updateValues",
            "host.DateTimeSystem.updateConfig",
            "host.SnmpSystem.reconfigureSnmpAgent",
            "host.ServiceSystem.start",
            "host.ServiceSystem.stop",
            "host.ServiceSystem.updatePolicy",
        ),
    ),
    ConfigChangeDefinition(
        kind="host_access",
        label="ホストのアクセスの設定の変更",
        event_types=(
            "esx.audit.ssh.enabled",
            "esx.audit.ssh.disabled",
            "esx.audit.shell.enabled",
            "esx.audit.shell.disabled",
            "esx.audit.dcui.enabled",
            "esx.audit.dcui.disabled",
            "esx.audit.lockdownmode.enabled",
            "esx.audit.lockdownmode.disabled",
            "esx.audit.net.firewall.disabled",
            "vim.event.LocalTSMEnabledEvent",
            "vim.event.RemoteTSMEnabledEvent",
        ),
        task_operations=(
            "host.FirewallSystem.enableRuleset",
            "host.FirewallSystem.disableRuleset",
            "host.FirewallSystem.updateRuleset",
            "host.FirewallSystem.updateDefaultPolicy",
            "HostSystem.enterLockdownMode",
            "HostSystem.exitLockdownMode",
        ),
    ),
    ConfigChangeDefinition(
        kind="permission",
        label="権限とロールの変更",
        event_types=(
            "vim.event.PermissionAddedEvent",
            "vim.event.PermissionRemovedEvent",
            "vim.event.PermissionUpdatedEvent",
            "vim.event.RoleAddedEvent",
            "vim.event.RoleRemovedEvent",
            "vim.event.RoleUpdatedEvent",
        ),
        task_operations=(
            "AuthorizationManager.setEntityPermissions",
            "AuthorizationManager.removeEntityPermission",
            "AuthorizationManager.resetEntityPermissions",
            "AuthorizationManager.addRole",
            "AuthorizationManager.removeRole",
            "AuthorizationManager.updateRole",
        ),
    ),
    ConfigChangeDefinition(
        kind="inventory",
        label="インベントリの変更",
        event_types=(
            "vim.event.HostAddedEvent",
            "vim.event.HostRemovedEvent",
            "vim.event.VmRenamedEvent",
            "vim.event.DatastoreRenamedEvent",
            "vim.event.DatacenterRenamedEvent",
            "vim.event.DvsRenamedEvent",
            "vim.event.DVPortgroupRenamedEvent",
        ),
        task_operations=(
            "ClusterComputeResource.addHost",
            "ClusterComputeResource.moveInto",
            "ClusterComputeResource.moveHostInto",
            "Folder.addStandaloneHost",
            "HostSystem.destroy",
            "ComputeResource.destroy",
            "VirtualMachine.rename",
            "Datastore.rename",
            "HostSystem.rename",
            "ClusterComputeResource.rename",
            "Datacenter.rename",
            "DistributedVirtualSwitch.rename",
            "dvs.VmwareDistributedVirtualSwitch.rename",
            "dvs.DistributedVirtualPortgroup.rename",
        ),
    ),
    ConfigChangeDefinition(
        kind="upgrade",
        label="アップグレード",
        event_types=(
            "vim.event.VmUpgradeCompleteEvent",
            "vim.event.DvsUpgradedEvent",
            "com.vmware.vcIntegrity.HostUpgradeProgressComplete",
            "com.vmware.vcIntegrity.InstallUpdateComplete",
        ),
        task_operations=(
            "VirtualMachine.upgradeTools",
            "VirtualMachine.upgradeVirtualHardware",
        ),
    ),
)
CONFIG_CHANGE_LABELS = {definition.kind: definition.label for definition in CONFIG_CHANGE_DEFINITIONS}
_KIND_BY_EVENT_TYPE = {
    event_type: definition.kind
    for definition in CONFIG_CHANGE_DEFINITIONS
    for event_type in (
        *definition.event_types,
        *(f"task.success.{operation}" for operation in definition.task_operations),
    )
}
CONFIG_CHANGE_EVENT_TYPES = frozenset(_KIND_BY_EVENT_TYPE)


def config_change_kind(event_type: str) -> str | None:
    """種別が完全一致する構成変更の種類を返す。"""
    return _KIND_BY_EVENT_TYPE.get(event_type)
