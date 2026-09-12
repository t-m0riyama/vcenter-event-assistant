# 出典表（priority v2）

イベント種別ガイドの本文は公式情報を **要約** したものです。転載ではありません。争いが生じた場合は **参照元の原文** を優先してください。

## 一次情報について

第2弾の本文は、**実機の vCenter Server 8.0 から取得したイベントカタログ**（`EventManager.description.eventInfo`、`ja` ロケール）を一次根拠としている。取得には [`scripts/dump_event_catalog.py`](../../scripts/dump_event_catalog.py) を使う。

このカタログは、イベント種別ごとに次を持つ。

- `description` — 公式の短い説明（日本語）
- `fullFormat` — 実際に記録されるメッセージのテンプレート（プロパティ名を含む）
- `longDescription` — `<description>` / `<cause>` / `<action>` を含む詳細説明（**一部の種別のみ**）
- `category` — 公式の重大度（`情報` / `警告` / `エラー` / `ユーザー`）

`action_required` は `category` を基準に決めている（`エラー` は原則 `true`、`警告` は個別判断、`情報` は原則 `false`）。ただし `情報` でも保護の喪失や強制停止を示すもの（`VmDasBeingResetEvent`、`VmPowerOffOnIsolationEvent`、`VmRestartedOnAlternateHostEvent` など）は例外として `true` にしている。

**取得したカタログ JSON は環境固有の情報を含みうるため、リポジトリにはコミットしない。**

## 列の意味

| 列 | 説明 |
|----|------|
| `event_type` | vCenter に記録される種別文字列。**アプリ・DB と完全一致**（大文字小文字・区切り含む） |
| `参照元` | 実際に参照した情報源。カタログのほか、公式ドキュメント／KB、日本語訳語の照合先 |
| `参照日` | 当方が内容を確認した日（YYYY-MM-DD） |
| `メモ` | カタログのどのフィールドを根拠にしたか、`category` の値 |

## 共通参照（イベント全般）

| event_type | 参照元 | 参照日 | メモ |
|------------|--------|--------|------|
| （共通） | https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere-sdks-tools/8-0/web-services-sdk-programming-guide/events-and-alarms/understanding-events.html | 2026-09-13 | Event データオブジェクトの概要、永続化の考え方 |
| （共通） | https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | VMware 公式の日本語メッセージ 46 件の対訳。**ManageEngine による非公式資料**のため、訳語の照合にのみ使用 |

## 第2弾（イベント種別ごと）

全 436 件。

| event_type | 参照元 | 参照日 | メモ |
|------------|--------|--------|------|
| `vim.event.AccountCreatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.AccountRemovedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.AccountUpdatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.AdminPasswordNotChangedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`情報`。 |
| `vim.event.AlarmAcknowledgedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.AlarmActionTriggeredEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.AlarmClearedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.AlarmCreatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.AlarmEmailCompletedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.AlarmEmailFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.AlarmEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.AlarmReconfiguredEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.AlarmRemovedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.AlarmScriptCompleteEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.AlarmScriptFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.AlarmSnmpCompletedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.AlarmSnmpFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.AlarmStatusChangedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.AllVirtualMachinesLicensedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.AlreadyAuthenticatedSessionEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.AuthorizationEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.BadUsernameSessionEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.CanceledHostOperationEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.ClusterComplianceCheckedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.ClusterCreatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ClusterDestroyedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ClusterEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ClusterOvercommittedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.ClusterReconfiguredEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ClusterStatusChangedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`情報`。 |
| `vim.event.CustomFieldDefAddedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.CustomFieldDefEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.CustomFieldDefRemovedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.CustomFieldDefRenamedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.CustomFieldEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.CustomFieldValueChangedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.CustomizationEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.CustomizationFailed` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.CustomizationLinuxIdentityFailed` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.CustomizationNetworkSetupFailed` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.CustomizationStartedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.CustomizationSucceeded` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.CustomizationSysprepFailed` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.CustomizationUnknownFailure` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.DVPortgroupCreatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DVPortgroupDestroyedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DVPortgroupEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DVPortgroupReconfiguredEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DVPortgroupRenamedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DasAdmissionControlDisabledEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DasAdmissionControlEnabledEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DasAgentFoundEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DasAgentUnavailableEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.DasClusterIsolatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.DasDisabledEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DasEnabledEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DasHostFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.DasHostIsolatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`警告`。 |
| `vim.event.DatacenterCreatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DatacenterEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DatacenterRenamedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DatastoreCapacityIncreasedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DatastoreDestroyedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.DatastoreDiscoveredEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.DatastoreDuplicatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.DatastoreEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DatastoreFileCopiedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DatastoreFileDeletedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DatastoreFileEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DatastoreFileMovedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DatastoreIORMReconfiguredEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DatastorePrincipalConfigured` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DatastoreRemovedOnHostEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.DatastoreRenamedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.DatastoreRenamedOnHostEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.DrsDisabledEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DrsEnabledEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DrsEnteredStandbyModeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DrsEnteringStandbyModeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DrsExitStandbyModeFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.DrsExitedStandbyModeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DrsExitingStandbyModeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DrsInvocationFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.DrsRecoveredFromFailureEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DrsResourceConfigureFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.DrsResourceConfigureSyncedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DrsRuleComplianceEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DrsRuleViolationEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DrsSoftRuleViolationEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DrsVmMigratedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.DrsVmPoweredOnEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.DuplicateIpDetectedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvpgImportEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvpgRestoreEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsCreatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsDestroyedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsHealthStatusChangeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsHostBackInSyncEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsHostJoinedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsHostLeftEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsHostStatusUpdated` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsHostWentOutOfSyncEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`警告`。 |
| `vim.event.DvsImportEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsMergedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsPortBlockedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsPortConnectedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsPortCreatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsPortDeletedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsPortDisconnectedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsPortEnteredPassthruEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsPortExitedPassthruEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsPortJoinPortgroupEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsPortLeavePortgroupEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsPortLinkDownEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsPortLinkUpEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsPortReconfiguredEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsPortRuntimeChangeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsPortUnblockedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsPortVendorSpecificStateChangeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsReconfiguredEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsRenamedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsRestoreEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsUpgradeAvailableEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsUpgradeInProgressEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsUpgradeRejectedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.DvsUpgradedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.EnteredMaintenanceModeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.EnteredStandbyModeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.EnteringMaintenanceModeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.EnteringStandbyModeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ErrorUpgradeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.EventEx` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`（なし）`。 |
| `vim.event.ExitMaintenanceModeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ExitStandbyModeFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.ExitedStandbyModeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ExitingStandbyModeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ExtendedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/8.0/vim.event.ExtendedEvent.html | 2026-09-13 | 型定義のみ（カタログ未収録の基底型）。 |
| `vim.event.FailoverLevelRestored` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.GeneralEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.GeneralHostErrorEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`エラー`。 |
| `vim.event.GeneralHostInfoEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.GeneralHostWarningEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`警告`。 |
| `vim.event.GeneralUserEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`ユーザー`。 |
| `vim.event.GeneralVmErrorEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.GeneralVmInfoEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.GeneralVmWarningEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`警告`。 |
| `vim.event.GhostDvsProxySwitchDetectedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.GhostDvsProxySwitchRemovedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.GlobalMessageChangedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HealthStatusChangedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostAddFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.HostAddedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.HostAdminDisableEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`警告`。 |
| `vim.event.HostAdminEnableEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`警告`。 |
| `vim.event.HostCnxFailedAccountFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`エラー`。 |
| `vim.event.HostCnxFailedAlreadyManagedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostCnxFailedBadCcagentEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostCnxFailedBadUsernameEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostCnxFailedBadVersionEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostCnxFailedCcagentUpgradeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostCnxFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`エラー`。 |
| `vim.event.HostCnxFailedNetworkErrorEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostCnxFailedNoAccessEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostCnxFailedNoConnectionEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostCnxFailedNoLicenseEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostCnxFailedNotFoundEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostCnxFailedTimeoutEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`エラー`。 |
| `vim.event.HostComplianceCheckedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.HostCompliantEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostConfigAppliedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostConnectedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.HostConnectionLostEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`エラー`。 |
| `vim.event.HostDasDisabledEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostDasDisablingEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostDasEnabledEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostDasEnablingEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`警告`。 |
| `vim.event.HostDasErrorEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.HostDasEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostDasOkEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostEnableAdminFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.HostEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostExtraNetworksEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostGetShortNameFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostInAuditModeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostInventoryFullEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostInventoryUnreadableEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostIpChangedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.HostIpInconsistentEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.HostIpToShortNameFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostIsolationIpPingFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostLicenseExpiredEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostLocalPortCreatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostMissingNetworksEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostMonitoringStateChangedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostNoAvailableNetworksEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostNoHAEnabledPortGroupsEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostNoRedundantManagementNetworkEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`警告`。 |
| `vim.event.HostNonCompliantEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostNotInClusterEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.HostOvercommittedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostPrimaryAgentNotShortNameEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostProfileAppliedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostReconnectionFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`エラー`。 |
| `vim.event.HostRemovedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostShortNameInconsistentEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostShortNameToIpFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.HostShutdownEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostSpecificationChangedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostSpecificationRequireEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostSpecificationUpdateEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostStatusChangedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`情報`。 |
| `vim.event.HostSubSpecificationDeleteEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostSubSpecificationUpdateEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostSyncFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`エラー`。 |
| `vim.event.HostUpgradeFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.HostUserWorldSwapNotEnabledEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`警告`。 |
| `vim.event.HostVnicConnectedToCustomizedDVPortEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.HostWwnChangedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`警告`。 |
| `vim.event.HostWwnConflictEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`エラー`。 |
| `vim.event.IncorrectHostInformationEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`エラー`。 |
| `vim.event.InfoUpgradeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.InsufficientFailoverResourcesEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.InvalidEditionEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.LicenseEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.LicenseExpiredEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.LicenseNonComplianceEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.LicenseRestrictedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.LicenseServerAvailableEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.LicenseServerUnavailableEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.LocalDatastoreCreatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.LocalTSMEnabledEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.LockerMisconfiguredEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`警告`。 |
| `vim.event.LockerReconfiguredEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.MigrationErrorEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.MigrationEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.MigrationHostErrorEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.MigrationHostWarningEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`警告`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.MigrationResourceErrorEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.MigrationResourceWarningEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`警告`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.MigrationWarningEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`警告`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.MtuMatchEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.MtuMismatchEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.NASDatastoreCreatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.NetworkRollbackEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.NoAccessUserEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.NoDatastoresConfiguredEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.NoLicenseEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.NoMaintenanceModeDrsRecommendationForVM` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`情報`。 |
| `vim.event.NonVIWorkloadDetectedOnDatastoreEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.NotEnoughResourcesToStartVmEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`警告`。 |
| `vim.event.OutOfSyncDvsHost` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`警告`。 |
| `vim.event.PermissionAddedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.PermissionEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.PermissionRemovedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.PermissionUpdatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ProfileAssociatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ProfileChangedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ProfileCreatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ProfileDissociatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ProfileEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ProfileReferenceHostChangedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ProfileRemovedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.RecoveryEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.RemoteTSMEnabledEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ResourcePoolCreatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ResourcePoolDestroyedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ResourcePoolEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ResourcePoolMovedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ResourcePoolReconfiguredEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ResourceViolatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.RoleAddedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.RoleEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.RoleRemovedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.RoleUpdatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.RollbackEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ScheduledTaskCompletedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ScheduledTaskCreatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ScheduledTaskEmailCompletedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ScheduledTaskEmailFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.ScheduledTaskEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ScheduledTaskFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.ScheduledTaskReconfiguredEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ScheduledTaskRemovedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ScheduledTaskStartedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.ServerLicenseExpiredEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.ServerStartedSessionEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.SessionEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.SessionTerminatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.TaskEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.TaskTimeoutEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.TeamingMatchEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.TeamingMisMatchEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.TemplateBeingUpgradedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.TemplateUpgradeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.TemplateUpgradeFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.TemplateUpgradedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.TimedOutHostOperationEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`警告`。 |
| `vim.event.UnlicensedVirtualMachinesEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.UnlicensedVirtualMachinesFoundEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.UpdatedAgentBeingRestartedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.UpgradeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.UplinkPortMtuNotSupportEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.UplinkPortMtuSupportEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.UplinkPortVlanTrunkedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.UplinkPortVlanUntrunkedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.UserAssignedToGroup` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.UserLoginSessionEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.UserLogoutSessionEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.UserPasswordChanged` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.UserUnassignedFromGroup` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.UserUpgradeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`ユーザー`。 |
| `vim.event.VMFSDatastoreCreatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VMFSDatastoreExpandedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.VMFSDatastoreExtendedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.VMotionLicenseExpiredEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.VcAgentUninstallFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`エラー`。 |
| `vim.event.VcAgentUninstalledEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VcAgentUpgradeFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`エラー`。 |
| `vim.event.VcAgentUpgradedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VimAccountPasswordChangedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.VmAcquiredMksTicketEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.VmAcquiredTicketEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmAutoRenameEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.VmBeingClonedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmBeingClonedNoFolderEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmBeingCreatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmBeingDeployedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.VmBeingHotMigratedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.VmBeingMigratedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.VmBeingRelocatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.VmCloneEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmCloneFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`エラー`。 |
| `vim.event.VmClonedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmConfigMissingEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`情報`。 |
| `vim.event.VmConnectedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmCreatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmDasBeingResetEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`情報`。 |
| `vim.event.VmDasBeingResetWithScreenshotEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`情報`。 |
| `vim.event.VmDasResetFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`警告`。 |
| `vim.event.VmDasUpdateErrorEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.VmDasUpdateOkEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmDateRolledBackEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.VmDeployFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.VmDeployedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmDisconnectedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmDiscoveredEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmDiskFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmEmigratingEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmEndRecordingEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmEndReplayingEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmFailedMigrateEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmFailedRelayoutEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.VmFailedRelayoutOnVmfs2DatastoreEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.VmFailedStartingSecondaryEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.VmFailedToPowerOffEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmFailedToPowerOnEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmFailedToRebootGuestEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmFailedToResetEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.VmFailedToShutdownGuestEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.VmFailedToStandbyGuestEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.VmFailedToSuspendEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmFailedUpdatingSecondaryConfig` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`エラー`。 |
| `vim.event.VmFailoverFailed` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`警告`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmFaultToleranceStateChangedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.VmFaultToleranceTurnedOffEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.VmFaultToleranceVmTerminatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`情報`。 |
| `vim.event.VmGuestOSCrashedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.VmGuestRebootEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmGuestStandbyEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmHealthMonitoringStateChangedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmInstanceUuidAssignedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.VmInstanceUuidChangedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.VmInstanceUuidConflictEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`エラー`。 |
| `vim.event.VmMacAssignedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmMacChangedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`警告`。 |
| `vim.event.VmMacConflictEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`エラー`。 |
| `vim.event.VmMaxFTRestartCountReached` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`警告`。 |
| `vim.event.VmMaxRestartCountReached` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`警告`。 |
| `vim.event.VmMessageErrorEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`エラー`。 |
| `vim.event.VmMessageEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.VmMessageWarningEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`警告`。 |
| `vim.event.VmMigratedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmNoCompatibleHostForSecondaryEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.VmNoNetworkAccessEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`警告`。 |
| `vim.event.VmOrphanedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`警告`。 |
| `vim.event.VmPowerOffOnIsolationEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmPoweringOnWithCustomizedDVPortEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmPrimaryFailoverEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmReconfiguredEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmRegisteredEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmRelayoutSuccessfulEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmRelayoutUpToDateEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmReloadFromPathEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmReloadFromPathFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.VmRelocateFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmRelocateSpecEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmRemoteConsoleConnectedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmRemoteConsoleDisconnectedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmRemovedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmRenamedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`警告`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmRequirementsExceedCurrentEVCModeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`警告`。 |
| `vim.event.VmResettingEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmResourcePoolMovedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmResourceReallocatedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmRestartedOnAlternateHostEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmResumingEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmSecondaryAddedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmSecondaryDisabledBySystemEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.VmSecondaryDisabledEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmSecondaryEnabledEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmSecondaryStartedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmShutdownOnIsolationEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmStartRecordingEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmStartReplayingEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmStartingEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmStartingSecondaryEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmStaticMacConflictEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.VmStoppingEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmSuspendingEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmTimedoutStartingSecondaryEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.VmUnsupportedStartingEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`警告`。 |
| `vim.event.VmUpgradeCompleteEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmUpgradeFailedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール）<br>https://www.manageengine.jp/support/kb/OpManager/?p=461 | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。日本語訳語を ManageEngine KB（**非公式の補助資料**）と照合。 |
| `vim.event.VmUpgradingEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.VmUuidAssignedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.VmUuidChangedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`警告`。 |
| `vim.event.VmUuidConflictEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`エラー`。 |
| `vim.event.VmVnicPoolReservationViolationClearEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmVnicPoolReservationViolationRaiseEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`情報`。 |
| `vim.event.VmWwnAssignedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`情報`。 |
| `vim.event.VmWwnChangedEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因）。category=`警告`。 |
| `vim.event.VmWwnConflictEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `longDescription`（説明・原因・対処）。category=`エラー`。 |
| `vim.event.WarningUpgradeEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`警告`。 |
| `vim.event.iScsiBootFailureEvent` | vCenter イベントカタログ（`EventManager.description.eventInfo`, vSphere 8.0, ja ロケール） | 2026-09-13 | 公式の `description` と `fullFormat`。category=`警告`。 |

## 実在しない種別の削除（2026-09-13）

第2弾シードには、**vSphere API に実在しない `event_type` が 27 件**含まれていた（`vim.event.SnapshotCreatedEvent`、`vim.event.HostKernelPanicEvent`、`vim.event.VmMigrationFailedEvent` など）。いずれも実機のカタログにも pyVmomi の型定義にも存在せず、旧版の出典表に載っていた API リファレンス URL も型名から機械的に組み立てられたものだった。実在する対応型（`vim.event.VMFSDatastoreExpandedEvent`、`vim.event.HostIpChangedEvent` など）はすべてシードに収録済みのため、これら 27 件は削除した（463 → 436 件）。

削除した種別の一覧は Git の履歴（本ファイルおよびシード JSON の差分）から確認できる。

## 差分確認の手順

1. 対象 vCenter に対して `scripts/dump_event_catalog.py` を実行し、カタログを取得する。
2. シードの `event_type` とカタログの `event_type` を突き合わせ、増減を確認する。
3. `description` / `fullFormat` / `category` が変わった種別だけ、本文と本表の参照日を更新する。
