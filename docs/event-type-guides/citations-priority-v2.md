# 出典表（priority v2）

イベント種別ガイドの本文は公式ドキュメントを **要約** したものです。転載ではありません。争いが生じた場合は **参照 URL の原文** を優先してください。

## 列の意味

| 列 | 説明 |
|----|------|
| `event_type` | vCenter に記録される種別文字列。**アプリ・DB と完全一致**（大文字小文字・区切り含む） |
| `参照 URL` | Broadcom／VMware 公式（製品ドキュメント、Web Services API リファレンス、KB 等） |
| `参照日` | 当方が内容を確認した日（YYYY-MM-DD） |
| `メモ` | どの節・どの型定義を根拠にしたか、一言 |

## 共通参照（イベント全般）

| event_type | 参照 URL | 参照日 | メモ |
|------------|----------|--------|------|
| （共通） | https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere-sdks-tools/8-0/web-services-sdk-programming-guide/events-and-alarms/understanding-events.html | 2026-03-22 | Event データオブジェクトの概要、永続化の考え方 |

## 第2弾（データオブジェクト別）

| event_type | 参照 URL | 参照日 | メモ |
|------------|----------|--------|------|
| `vim.event.AlarmAcknowledgedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.AlarmAcknowledgedEvent.html | 2026-03-22 | Data Object Description（`AlarmAcknowledgedEvent`） |
| `vim.event.AlarmActionTriggeredEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.AlarmActionTriggeredEvent.html | 2026-03-22 | Data Object Description（`AlarmActionTriggeredEvent`） |
| `vim.event.AlarmClearedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.AlarmClearedEvent.html | 2026-03-22 | Data Object Description（`AlarmClearedEvent`） |
| `vim.event.AlarmCreatedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.AlarmCreatedEvent.html | 2026-03-22 | Data Object Description（`AlarmCreatedEvent`） |
| `vim.event.AlarmEmailCompletedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.AlarmEmailCompletedEvent.html | 2026-03-22 | Data Object Description（`AlarmEmailCompletedEvent`） |
| `vim.event.AlarmEmailFailedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.AlarmEmailFailedEvent.html | 2026-03-22 | Data Object Description（`AlarmEmailFailedEvent`） |
| `vim.event.AlarmStatusChangedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.AlarmStatusChangedEvent.html | 2026-03-22 | Data Object Description（`AlarmStatusChangedEvent`） |
| `vim.event.ClusterComplianceCheckedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.ClusterComplianceCheckedEvent.html | 2026-03-22 | Data Object Description（`ClusterComplianceCheckedEvent`） |
| `vim.event.ClusterCreatedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.ClusterCreatedEvent.html | 2026-03-22 | Data Object Description（`ClusterCreatedEvent`） |
| `vim.event.ClusterDasAdmissionControlFailedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.ClusterDasAdmissionControlFailedEvent.html | 2026-03-22 | Data Object Description（`ClusterDasAdmissionControlFailedEvent`） |
| `vim.event.ClusterDestroyedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.ClusterDestroyedEvent.html | 2026-03-22 | Data Object Description（`ClusterDestroyedEvent`） |
| `vim.event.ClusterOvercommittedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.ClusterOvercommittedEvent.html | 2026-03-22 | Data Object Description（`ClusterOvercommittedEvent`） |
| `vim.event.ClusterReconfiguredEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.ClusterReconfiguredEvent.html | 2026-03-22 | Data Object Description（`ClusterReconfiguredEvent`） |
| `vim.event.ComplianceProfileAssignedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.ComplianceProfileAssignedEvent.html | 2026-03-22 | Data Object Description（`ComplianceProfileAssignedEvent`） |
| `vim.event.CustomizationFailed` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.CustomizationFailed.html | 2026-03-22 | Data Object Description（`CustomizationFailed`） |
| `vim.event.CustomizationStartedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.CustomizationStartedEvent.html | 2026-03-22 | Data Object Description（`CustomizationStartedEvent`） |
| `vim.event.CustomizationSucceeded` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.CustomizationSucceeded.html | 2026-03-22 | Data Object Description（`CustomizationSucceeded`） |
| `vim.event.CustomizationSysprepFailed` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.CustomizationSysprepFailed.html | 2026-03-22 | Data Object Description（`CustomizationSysprepFailed`） |
| `vim.event.DVPortgroupCreatedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.DVPortgroupCreatedEvent.html | 2026-03-22 | Data Object Description（`DVPortgroupCreatedEvent`） |
| `vim.event.DVPortgroupDestroyedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.DVPortgroupDestroyedEvent.html | 2026-03-22 | Data Object Description（`DVPortgroupDestroyedEvent`） |
| `vim.event.DVPortgroupReconfiguredEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.DVPortgroupReconfiguredEvent.html | 2026-03-22 | Data Object Description（`DVPortgroupReconfiguredEvent`） |
| `vim.event.DasAdmissionControlDisabledEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.DasAdmissionControlDisabledEvent.html | 2026-03-22 | Data Object Description（`DasAdmissionControlDisabledEvent`） |
| `vim.event.DasClusterFailedHostEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.DasClusterFailedHostEvent.html | 2026-03-22 | Data Object Description（`DasClusterFailedHostEvent`） |
| `vim.event.DasClusterIsolatedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.DasClusterIsolatedEvent.html | 2026-03-22 | Data Object Description（`DasClusterIsolatedEvent`） |
| `vim.event.DasEnabledEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.DasEnabledEvent.html | 2026-03-22 | Data Object Description（`DasEnabledEvent`） |
| `vim.event.DasHostIsolatedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.DasHostIsolatedEvent.html | 2026-03-22 | Data Object Description（`DasHostIsolatedEvent`） |
| `vim.event.DatastoreCapacityIncreasedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.DatastoreCapacityIncreasedEvent.html | 2026-03-22 | Data Object Description（`DatastoreCapacityIncreasedEvent`） |
| `vim.event.DatastoreDestroyedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.DatastoreDestroyedEvent.html | 2026-03-22 | Data Object Description（`DatastoreDestroyedEvent`） |
| `vim.event.DatastoreFileMovedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.DatastoreFileMovedEvent.html | 2026-03-22 | Data Object Description（`DatastoreFileMovedEvent`） |
| `vim.event.DatastoreIORMReconfiguredEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.DatastoreIORMReconfiguredEvent.html | 2026-03-22 | Data Object Description（`DatastoreIORMReconfiguredEvent`） |
| `vim.event.DatastorePrincipalUpdated` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.DatastorePrincipalUpdated.html | 2026-03-22 | Data Object Description（`DatastorePrincipalUpdated`） |
| `vim.event.DatastoreRenamedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.DatastoreRenamedEvent.html | 2026-03-22 | Data Object Description（`DatastoreRenamedEvent`） |
| `vim.event.DrsResourcePoolVmMovedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.DrsResourcePoolVmMovedEvent.html | 2026-03-22 | Data Object Description（`DrsResourcePoolVmMovedEvent`） |
| `vim.event.DrsResourcePoolVmRegisteredEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.DrsResourcePoolVmRegisteredEvent.html | 2026-03-22 | Data Object Description（`DrsResourcePoolVmRegisteredEvent`） |
| `vim.event.DrsResourcePoolVmUnregisteredEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.DrsResourcePoolVmUnregisteredEvent.html | 2026-03-22 | Data Object Description（`DrsResourcePoolVmUnregisteredEvent`） |
| `vim.event.DrsVmMigratedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.DrsVmMigratedEvent.html | 2026-03-22 | Data Object Description（`DrsVmMigratedEvent`） |
| `vim.event.DrsVmPoweredOffEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.DrsVmPoweredOffEvent.html | 2026-03-22 | Data Object Description（`DrsVmPoweredOffEvent`） |
| `vim.event.DrsVmPoweredOnEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.DrsVmPoweredOnEvent.html | 2026-03-22 | Data Object Description（`DrsVmPoweredOnEvent`） |
| `vim.event.EnteringMaintenanceModeEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.EnteringMaintenanceModeEvent.html | 2026-03-22 | Data Object Description（`EnteringMaintenanceModeEvent`） |
| `vim.event.ExitingMaintenanceModeEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.ExitingMaintenanceModeEvent.html | 2026-03-22 | Data Object Description（`ExitingMaintenanceModeEvent`） |
| `vim.event.HostAddedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostAddedEvent.html | 2026-03-22 | Data Object Description（`HostAddedEvent`） |
| `vim.event.HostAddedToClusterEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostAddedToClusterEvent.html | 2026-03-22 | Data Object Description（`HostAddedToClusterEvent`） |
| `vim.event.HostCertificateExpirationEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostCertificateExpirationEvent.html | 2026-03-22 | Data Object Description（`HostCertificateExpirationEvent`） |
| `vim.event.HostCertificateRenewedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostCertificateRenewedEvent.html | 2026-03-22 | Data Object Description（`HostCertificateRenewedEvent`） |
| `vim.event.HostCnxFailedAccountFailedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostCnxFailedAccountFailedEvent.html | 2026-03-22 | Data Object Description（`HostCnxFailedAccountFailedEvent`） |
| `vim.event.HostCnxFailedBadCcagentEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostCnxFailedBadCcagentEvent.html | 2026-03-22 | Data Object Description（`HostCnxFailedBadCcagentEvent`） |
| `vim.event.HostCnxFailedBadUsernameEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostCnxFailedBadUsernameEvent.html | 2026-03-22 | Data Object Description（`HostCnxFailedBadUsernameEvent`） |
| `vim.event.HostCnxFailedCcagentUpgradeEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostCnxFailedCcagentUpgradeEvent.html | 2026-03-22 | Data Object Description（`HostCnxFailedCcagentUpgradeEvent`） |
| `vim.event.HostCnxFailedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostCnxFailedEvent.html | 2026-03-22 | Data Object Description（`HostCnxFailedEvent`） |
| `vim.event.HostCnxFailedNetworkErrorEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostCnxFailedNetworkErrorEvent.html | 2026-03-22 | Data Object Description（`HostCnxFailedNetworkErrorEvent`） |
| `vim.event.HostCnxFailedNoConnectionEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostCnxFailedNoConnectionEvent.html | 2026-03-22 | Data Object Description（`HostCnxFailedNoConnectionEvent`） |
| `vim.event.HostConnectedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostConnectedEvent.html | 2026-03-22 | Data Object Description（`HostConnectedEvent`） |
| `vim.event.HostIPAddressChangedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostIPAddressChangedEvent.html | 2026-03-22 | Data Object Description（`HostIPAddressChangedEvent`） |
| `vim.event.HostKernelPanicEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostKernelPanicEvent.html | 2026-03-22 | Data Object Description（`HostKernelPanicEvent`） |
| `vim.event.HostLicenseExpiredEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostLicenseExpiredEvent.html | 2026-03-22 | Data Object Description（`HostLicenseExpiredEvent`） |
| `vim.event.HostNotInClusterEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostNotInClusterEvent.html | 2026-03-22 | Data Object Description（`HostNotInClusterEvent`） |
| `vim.event.HostReconnectionFailedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostReconnectionFailedEvent.html | 2026-03-22 | Data Object Description（`HostReconnectionFailedEvent`） |
| `vim.event.HostRemovedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostRemovedEvent.html | 2026-03-22 | Data Object Description（`HostRemovedEvent`） |
| `vim.event.HostRemovedFromClusterEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostRemovedFromClusterEvent.html | 2026-03-22 | Data Object Description（`HostRemovedFromClusterEvent`） |
| `vim.event.HostShutdownEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostShutdownEvent.html | 2026-03-22 | Data Object Description（`HostShutdownEvent`） |
| `vim.event.HostSpecificationChangedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostSpecificationChangedEvent.html | 2026-03-22 | Data Object Description（`HostSpecificationChangedEvent`） |
| `vim.event.HostSyncFailedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostSyncFailedEvent.html | 2026-03-22 | Data Object Description（`HostSyncFailedEvent`） |
| `vim.event.HostVnicReconfiguredEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostVnicReconfiguredEvent.html | 2026-03-22 | Data Object Description（`HostVnicReconfiguredEvent`） |
| `vim.event.LicenseExpiredEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.LicenseExpiredEvent.html | 2026-03-22 | Data Object Description（`LicenseExpiredEvent`） |
| `vim.event.NasDatastoreMountedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.NasDatastoreMountedEvent.html | 2026-03-22 | Data Object Description（`NasDatastoreMountedEvent`） |
| `vim.event.ScheduledTaskCompletedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.ScheduledTaskCompletedEvent.html | 2026-03-22 | Data Object Description（`ScheduledTaskCompletedEvent`） |
| `vim.event.ScheduledTaskStartedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.ScheduledTaskStartedEvent.html | 2026-03-22 | Data Object Description（`ScheduledTaskStartedEvent`） |
| `vim.event.SnapshotCreatedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.SnapshotCreatedEvent.html | 2026-03-22 | Data Object Description（`SnapshotCreatedEvent`） |
| `vim.event.SnapshotRemovedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.SnapshotRemovedEvent.html | 2026-03-22 | Data Object Description（`SnapshotRemovedEvent`） |
| `vim.event.SnapshotRestoredEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.SnapshotRestoredEvent.html | 2026-03-22 | Data Object Description（`SnapshotRestoredEvent`） |
| `vim.event.TaskEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.TaskEvent.html | 2026-03-22 | Data Object Description（`TaskEvent`） |
| `vim.event.VmAcquiringMksTicketEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmAcquiringMksTicketEvent.html | 2026-03-22 | Data Object Description（`VmAcquiringMksTicketEvent`） |
| `vim.event.VmBeingCreatedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmBeingCreatedEvent.html | 2026-03-22 | Data Object Description（`VmBeingCreatedEvent`） |
| `vim.event.VmClonedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmClonedEvent.html | 2026-03-22 | Data Object Description（`VmClonedEvent`） |
| `vim.event.VmConfigMissingEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmConfigMissingEvent.html | 2026-03-22 | Data Object Description（`VmConfigMissingEvent`） |
| `vim.event.VmConfigQuestionEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmConfigQuestionEvent.html | 2026-03-22 | Data Object Description（`VmConfigQuestionEvent`） |
| `vim.event.VmCreatedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmCreatedEvent.html | 2026-03-22 | Data Object Description（`VmCreatedEvent`） |
| `vim.event.VmDeployFailedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmDeployFailedEvent.html | 2026-03-22 | Data Object Description（`VmDeployFailedEvent`） |
| `vim.event.VmDeployedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmDeployedEvent.html | 2026-03-22 | Data Object Description（`VmDeployedEvent`） |
| `vim.event.VmDiscoveredEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmDiscoveredEvent.html | 2026-03-22 | Data Object Description（`VmDiscoveredEvent`） |
| `vim.event.VmFailedToPowerOnEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmFailedToPowerOnEvent.html | 2026-03-22 | Data Object Description（`VmFailedToPowerOnEvent`） |
| `vim.event.VmFailedToSuspendEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmFailedToSuspendEvent.html | 2026-03-22 | Data Object Description（`VmFailedToSuspendEvent`） |
| `vim.event.VmFailoverEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmFailoverEvent.html | 2026-03-22 | Data Object Description（`VmFailoverEvent`） |
| `vim.event.VmGuestRebootEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmGuestRebootEvent.html | 2026-03-22 | Data Object Description（`VmGuestRebootEvent`） |
| `vim.event.VmGuestShutdownFailedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmGuestShutdownFailedEvent.html | 2026-03-22 | Data Object Description（`VmGuestShutdownFailedEvent`） |
| `vim.event.VmInstanceUuidAssignedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmInstanceUuidAssignedEvent.html | 2026-03-22 | Data Object Description（`VmInstanceUuidAssignedEvent`） |
| `vim.event.VmInstanceUuidConflictEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmInstanceUuidConflictEvent.html | 2026-03-22 | Data Object Description（`VmInstanceUuidConflictEvent`） |
| `vim.event.VmMigrationFailedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmMigrationFailedEvent.html | 2026-03-22 | Data Object Description（`VmMigrationFailedEvent`） |
| `vim.event.VmReconfiguredEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmReconfiguredEvent.html | 2026-03-22 | Data Object Description（`VmReconfiguredEvent`） |
| `vim.event.VmRegisteredEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmRegisteredEvent.html | 2026-03-22 | Data Object Description（`VmRegisteredEvent`） |
| `vim.event.VmRelocateFailedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmRelocateFailedEvent.html | 2026-03-22 | Data Object Description（`VmRelocateFailedEvent`） |
| `vim.event.VmRemoteConsoleConnectedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmRemoteConsoleConnectedEvent.html | 2026-03-22 | Data Object Description（`VmRemoteConsoleConnectedEvent`） |
| `vim.event.VmRemovedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmRemovedEvent.html | 2026-03-22 | Data Object Description（`VmRemovedEvent`） |
| `vim.event.VmRenamedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmRenamedEvent.html | 2026-03-22 | Data Object Description（`VmRenamedEvent`） |
| `vim.event.VmResettingEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmResettingEvent.html | 2026-03-22 | Data Object Description（`VmResettingEvent`） |
| `vim.event.VmSecondaryAddedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmSecondaryAddedEvent.html | 2026-03-22 | Data Object Description（`VmSecondaryAddedEvent`） |
| `vim.event.VmSecondaryDisabledEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmSecondaryDisabledEvent.html | 2026-03-22 | Data Object Description（`VmSecondaryDisabledEvent`） |
| `vim.event.VmStartingEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmStartingEvent.html | 2026-03-22 | Data Object Description（`VmStartingEvent`） |
| `vim.event.VmTimedoutStartingEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmTimedoutStartingEvent.html | 2026-03-22 | Data Object Description（`VmTimedoutStartingEvent`） |
| `vim.event.VmfsDatastoreExpandedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmfsDatastoreExpandedEvent.html | 2026-03-22 | Data Object Description（`VmfsDatastoreExpandedEvent`） |

**注:** API リファレンスは **vSphere Web Services API 7.0** のページを使用（型定義の説明はバージョン間で共通部分が多い）。より新しい API バージョンの同型ページが利用可能な場合は、チーム方針に合わせて差し替えてよい。
