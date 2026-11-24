# 構成変更を目立たせる（タイムライン）

最終更新: 2026-11-25（全 PR マージ済み）

[障害調査を楽にする機能 10 案](2026-11-22-troubleshooting-ideas.md)（以下「10 案」）の「案 2a」（構成変更の追跡の第 1 段）にあたる。すでに集めている構成変更のイベントとタスクを、タイムラインで目立たせる。[AI活用アイデア20案](2026-05-07-ai-idea-backlog-20.md) の 9 番「変更イベント相関分析」と同じ方向である。Issue は起票していない。

コードの場所は、バックエンドを `src/vcenter_event_assistant/` から、画面を `frontend/src/` から書く。行番号は、本書を書いた時点の origin/main（8a00f63）のものである。

## 進捗

| PR | 内容 | 状態 |
|---|---|---|
| A | 本書 | マージ済み [PR #374](https://github.com/t-m0riyama/vcenter-event-assistant/pull/374) |
| B | 構成変更の定義と API（ハイライト・行の印・出力） | マージ済み [PR #375](https://github.com/t-m0riyama/vcenter-event-assistant/pull/375) |
| C | 画面（ハイライトのカードと行の印）と文書 | マージ済み [PR #376](https://github.com/t-m0riyama/vcenter-event-assistant/pull/376) |

各 PR は単独でマージでき、テストが通る状態にする。

## Context

障害の調査では、まず「直前に何を変えたか」を知りたい。VM の再構成、メンテナンスモード、クラスタの HA・DRS の設定、分散スイッチの設定、権限などである。こうした変更のイベントとタスクは、すでに集めている。ただし、タイムラインではほぼ見えない。

- 構成変更のイベントは、ほとんどが 0 点になる。スコアの重大度の点（`rules/notable.py:23-28` の `SEVERITY_WEIGHT`）は、重大度を持つ EventEx にしか付かないためである（`collectors/events.py:139` は `getattr(e, "severity", None)` で取る）。タイムラインは既定で最小スコア 1 以上だけを出すので、一覧にもハイライトにも出ない。
- 案 3a で入ったタスクの成功（`task.success.*`）も、0 点なので同じく出ない。

決めたこと（利用者の決定）:
- **見せ方:** ハイライトに「構成変更」のカードを足す。期間の中（起点があれば起点まで）の構成変更を、最小スコアに関係なく並べる。時系列の一覧にも、その行を最小スコアに関係なく含め、「構成変更」の印を付ける。
- **対象:** 本体に組み込みの固定の一覧で決める（案 5 の障害パターンと同じ考え方）。設定の画面での編集はしない。
- **タスク:** 構成を変える操作の成功（`task.success.<操作>`）だけを含める。同じ変更のイベントとタスクの 2 行は、カードでは 1 件にまとめる。

検出の仕組みは、利用者と運用者向けに [構成変更の検出の仕組み](../features/config-change-detection.md) にまとめた（本書と同じ PR で足す）。設計の判断と細部の正本は本書とする。

10 案の計画書の注意を引き継ぐ。ここで扱うのは、vCenter が出したイベントとタスクから分かる変更だけである。設定の値の差分（何から何に変えたか）は扱わない。差分は案 2b（第 2 段）で扱う。

## 1. 前提（コードで確かめたこと）

- **イベントの種別:** `event_type` は pyVmomi の型名（`vim.event.VmReconfiguredEvent` など）である。EventEx と ExtendedEvent は `eventTypeId`（`esx.audit.ssh.enabled` など）になる（Issue #346）。
- **タスクの種別:** `task.<結果>.<操作>` の形である（`collectors/tasks.py:116,135`）。操作は `TaskInfo.descriptionId`（`VirtualMachine.reconfigure` など）で、空なら `name` から取る（`tasks.py:56-66`）。
  - 同じ操作でも、呼んだ対象の型ごとに名前が違う。vCenter のタスクの説明の一覧（`TaskManager.description.methodInfo`）を vcsim から読むと 1,578 件あり、次のように分かれていた。
    - `ClusterComputeResource.reconfigureEx` と `ComputeResource.reconfigureEx`
    - `DistributedVirtualSwitch.reconfigure` と `dvs.VmwareDistributedVirtualSwitch.reconfigure`
  - vcsim が実際に作るタスクの `descriptionId` は、`VirtualMachine.reconfigVm`・`ClusterComputeResource.reconfigureCluster` のように、この一覧と違う形だった（vcsim は Go の関数名から作る）。本書は、一覧（実機の vCenter から写したもの）の形が実機のタスクの `descriptionId` だとみなす。これは確かめていない前提である（8 章、PR B のマージの前に確かめる）。
- **chain_id:** イベントは `chainId` を（`events.py:135-137`）、タスクは `eventChainId` を（`tasks.py:146-148`。範囲の外なら None）、同じ `chain_id` 列に入れる。タスクから生まれたイベントは、タスクの `eventChainId` と同じ `chainId` を持つ。ホストが出す `esx.audit.*` は、タスクの chain に入らない。組み込みのコレクタの ID は `builtin.vcenter.events` と `builtin.vcenter.tasks` である（`plugins/builtin.py:59,97`）。
- **利用者:** イベントは `userName` を、タスクは `reason.userName` を `user_name` 列に入れる（`collectors/events.py:146`、`tasks.py:138-140`）。イベントの一覧の API（`EventRead.user_name`、`api/schemas/events.py:33`）では、viewer もすでに見られる。タイムラインの一覧の SELECT は、今は `user_name` を読んでいない。
- **イベントの集め方**（`services/incident_timeline_view.py`）:
  - `_collect_events`（991 行）は、俯瞰の件数を GROUP BY で数える。一覧の行は `notable_score >= min_score` で読む（1038 行）。行数が `max_rows` を超えると、ビュー全体が 422 になる（1043-1044 行）。期間の条件は `_event_filters` で、終わりは `< to` である（起点では切らない）。
  - 「新しい種別」は、集めた行から作る（`summarize_event_types`、716 行。`_build_in_slot` の 881-885 行）。案 3a の計画書は、0 点の `task.success.*` が既定ではここに出ないことを前提にしている（`docs/plans/2026-11-24-task-results.md:149`）。
  - まとめ（`merge_consecutive`、480 行）は、全種別を時刻順に並べた列で、`merge_key` が同じ隣どうしの行だけをまとめる。イベントの `merge_key` は（種別、対象の名前、vCenter、moid、level）で、スコアを含まない（1065 行）。
  - 「影響の大きい対象」は、まとめた後の全行から数える（`top_entities(merged)`、652・902 行）。ログは、まとめた行の数で数える。
  - 「最初の兆候」は、`is_signal` が真で warning 以上の最も早い行である（`first_signal`、616 行）。
  - 一覧の打ち切り（`select_within_limit`、561 行）:
    - 起点なし: level の重い順。ログ以外の行があるかぎり、枠の 4 分の 1 をそれらに残す（546-547 行）。
    - 起点あり: 起点からの距離の近い順（589-599 行）。
  - 検知した障害パターンは、全件から上限まで選び、総数を別に返す（`detected_patterns` と `detected_patterns_total`、905-909 行）。
- **スキーマ**（`api/schemas/incident_timeline_view.py`）: `IncidentTimelineViewItem`（161 行）、`IncidentTimelineHighlights`（226 行）。
- **保存した結果:** スナップショットの `result_payload` は、今のスキーマで読めなければ None になる（`api/routes/incident_timeline.py:142` の `_result_for_response`）。足す項目に既定値が無いと、保存済みの結果が読めなくなる。
- **出力（案 10）:** `services/incident_timeline_export.py`。
  - 報告書のハイライトは `_highlights`（249 行）で作る。
  - `items.csv` は `item.model_dump()` を `csv.DictWriter(fieldnames=_ITEM_COLUMNS)`（53・399 行）に渡す。`extrasaction` の既定は `raise` なので、項目に列を足したら `_ITEM_COLUMNS` にも足さないと失敗する。
  - `result.json` は結果をそのまま出す。
- **画面の起点:** 画面は起点を `toISOString()` でミリ秒に切り捨てて送る（`frontend/src/panels/timeline/useTimelineViewController.ts:470-471`）。`occurred_at` はマイクロ秒まで持つ。
- **チャット:** チャットに渡すタイムライン（`services/chat/`）は、ダイジェストの文脈とバケットから作り、ビューの結果（ハイライト）も `user_name` も使わない。

## 2. 構成変更の定義

`rules/config_changes.py`（新規。`rules/notable.py` の隣）に、固定の一覧を持つ。種類ごとに、表示名、イベントの種別、タスクの操作を持つ。タスクの操作は、成功の種別 `task.success.<操作>` として照合する。照合は完全一致だけにする。

イベントの種別は、vCenter のイベントの説明の一覧（`EventManager.description`、カタログの 2,196 件）に、タスクの操作は上のタスクの説明の一覧に、すべてあることを確かめた。

| 種類（`kind`） | 表示名 | イベント | タスクの操作 |
|---|---|---|---|
| `vm_reconfigure` | VM の構成変更 | `VmReconfiguredEvent` | `VirtualMachine.reconfigure` |
| `maintenance_enter` | メンテナンスモードに入った | `EnteringMaintenanceModeEvent`・`EnteredMaintenanceModeEvent`・`esx.audit.maintenancemode.entering`・`esx.audit.maintenancemode.entered`・`com.vmware.vc.sdrs.DatastoreEnteringMaintenanceModeEvent`・`com.vmware.vc.sdrs.DatastoreEnteredMaintenanceModeEvent` | `HostSystem.enterMaintenanceMode`・`Datastore.enterMaintenanceMode` |
| `maintenance_exit` | メンテナンスモードを出た | `ExitMaintenanceModeEvent`・`esx.audit.maintenancemode.exited`・`com.vmware.vc.sdrs.DatastoreExitedMaintenanceModeEvent` | `HostSystem.exitMaintenanceMode`・`Datastore.exitMaintenanceMode` |
| `cluster_config` | クラスタの設定の変更 | `ClusterReconfiguredEvent`・`DrsEnabledEvent`・`DrsDisabledEvent`・`DasEnabledEvent`・`DasDisabledEvent`・`DasAdmissionControlEnabledEvent`・`DasAdmissionControlDisabledEvent`・`com.vmware.vc.sdrs.StorageDrsDisabledEvent` | `ClusterComputeResource.reconfigureEx`・`ClusterComputeResource.reconfigure`・`ComputeResource.reconfigureEx` |
| `network_config` | ネットワークの設定の変更 | `DvsReconfiguredEvent`・`DVPortgroupReconfiguredEvent`・`DvsPortReconfiguredEvent`・`DVPortgroupCreatedEvent`・`DVPortgroupDestroyedEvent` | 分散スイッチ: `DistributedVirtualSwitch.reconfigure`・`.reconfigurePort`・`.addPortgroup`・`.addPortgroups`、同じ 4 つの `dvs.VmwareDistributedVirtualSwitch.*`、`dvs.DistributedVirtualPortgroup.reconfigure`・`.destroy`。標準スイッチ: `host.NetworkSystem.updateNetworkConfig`・`.updateVirtualSwitch`・`.addVirtualSwitch`・`.removeVirtualSwitch`・`.updatePortGroup`・`.addPortGroup`・`.removePortGroup`・`.updateDnsConfig`・`.updateIpRouteConfig` |
| `storage_config` | ストレージの設定の変更 | `DatastoreIORMReconfiguredEvent` | `host.StorageSystem.setMultipathLunPolicy`・`.mountVmfsVolume`・`.unmountVmfsVolume` |
| `resource_config` | リソースの割り当ての変更 | `ResourcePoolReconfiguredEvent` | `ResourcePool.updateConfig`・`.updateChildResourceConfiguration`、`VirtualApp.updateConfig`・`.updateChildResourceConfiguration` |
| `host_config` | ホストの設定の変更 | `HostProfileAppliedEvent`・`esx.audit.usb.config.changed` | `profile.host.profileEngine.HostProfileManager.applyHostConfig`・`option.OptionManager.updateValues`・`host.DateTimeSystem.updateConfig`・`host.SnmpSystem.reconfigureSnmpAgent`・`host.ServiceSystem.start`・`.stop`・`.updatePolicy` |
| `host_access` | ホストのアクセスの設定の変更 | `esx.audit.ssh.enabled`・`.disabled`、`esx.audit.shell.enabled`・`.disabled`、`esx.audit.dcui.enabled`・`.disabled`、`esx.audit.lockdownmode.enabled`・`.disabled`、`esx.audit.net.firewall.disabled`、`LocalTSMEnabledEvent`・`RemoteTSMEnabledEvent` | `host.FirewallSystem.enableRuleset`・`.disableRuleset`・`.updateRuleset`・`.updateDefaultPolicy`、`HostSystem.enterLockdownMode`・`.exitLockdownMode` |
| `permission` | 権限とロールの変更 | `PermissionAddedEvent`・`PermissionRemovedEvent`・`PermissionUpdatedEvent`・`RoleAddedEvent`・`RoleRemovedEvent`・`RoleUpdatedEvent` | `AuthorizationManager.setEntityPermissions`・`.removeEntityPermission`・`.resetEntityPermissions`・`.addRole`・`.removeRole`・`.updateRole` |
| `inventory` | インベントリの変更 | `HostAddedEvent`・`HostRemovedEvent`・`VmRenamedEvent`・`DatastoreRenamedEvent`・`DatacenterRenamedEvent`・`DvsRenamedEvent`・`DVPortgroupRenamedEvent` | `ClusterComputeResource.addHost`・`.moveInto`・`.moveHostInto`、`Folder.addStandaloneHost`、`HostSystem.destroy`・`ComputeResource.destroy`、`VirtualMachine.rename`・`Datastore.rename`・`HostSystem.rename`・`ClusterComputeResource.rename`・`Datacenter.rename`・`DistributedVirtualSwitch.rename`・`dvs.VmwareDistributedVirtualSwitch.rename`・`dvs.DistributedVirtualPortgroup.rename` |
| `upgrade` | アップグレード | `VmUpgradeCompleteEvent`・`DvsUpgradedEvent`・`com.vmware.vcIntegrity.HostUpgradeProgressComplete`・`com.vmware.vcIntegrity.InstallUpdateComplete` | `VirtualMachine.upgradeTools`・`VirtualMachine.upgradeVirtualHardware` |

表の `vim.event.` の接頭辞は省いた。コードでは完全な種別で書く。`.disabled` などの省略は、直前の項目と同じ接頭辞を意味する。合計で、イベント 55 種別、タスクの操作 69 種類である。

- `host.ServiceSystem.start`・`.stop`・`.updatePolicy` は、SSH だけでなく NTP・SNMP などすべてのサービスに使われる。そのため、アクセスの設定（`host_access`）ではなく、ホストの設定（`host_config`）に入れる。

- 重大度の点が付くのは EventEx だけである（Context）。表の中では `esx.audit.*` などの EventEx が、重大度によっては点を持つ。たとえば `esx.audit.net.firewall.disabled` はカタログでは warning なので、20 点になれば今も最小スコア 1 で出る。点を持つ行にも印を付ける。
- 入れなかったもの:
  - `HostDasEnabledEvent`・`HostDasDisabledEvent`: HA の再構成や、メンテナンスモードからの復帰・再接続のたびに、ホストごとに出る。16 台のクラスタで HA を有効にすると 17 件になり、カードの上限を埋める。クラスタの変更は `DasEnabledEvent` などで分かる。
  - `HostSystem.reconfigureDAS`（ホストごとの vSphere HA の再構成のタスク）: HA を有効にしたときや、ホストを足して再接続したときに、ホストごとに自動で出る。対象はホストで chain も別なので、上と同じくカードが埋まる。
  - `VcAgentUpgradedEvent`: vCenter のアップグレードの後、全ホストで自動で出る。
  - vMotion・Storage vMotion（`VirtualMachine.relocate` など）: 移動であり、設定の変更ではない。障害パターン（案 5）が扱う。
  - スナップショットの作成・復元（`vm.Snapshot.revert` など）: 操作であり、件数も多い（バックアップの製品が作る）。復元は後続の候補にする（7 章）。
  - アラームとスケジュールタスクの再構成（`AlarmReconfiguredEvent` など）: 監視の設定であり、インフラの構成ではない。
  - VM の作成・削除・登録: 件数が多く、構成変更のカードが埋まる。
- 一覧は、この PR のあとも足せるように、種類ごとの定義（データクラスの組）にする。種別が 2 つの種類に入らないことを、テストで確かめる。

## 3. API（PR B）

リクエストは変えない。結果（`IncidentTimelineViewResponse`）に項目を足す。足す項目はすべて既定値を持たせ、保存済みのスナップショットの結果がそのまま読めるようにする。

### 集める範囲

- 構成変更の窓は、期間の始まりから「期間の終わり」と「起点」の早いほうまでとする。
  - 起点を終わりにするときは、起点ちょうどの行も含める。画面は起点をミリ秒に切り捨てて送るので、`occurred_at < 起点 + 1 ミリ秒` で比べる。カードの「ここを起点にする」を押した後も、押した変更が窓に残るようにするためである。
  - 起点が期間の始まりより前なら、窓は空になる。
- 種別（`sources`）に `event` が無いときは集めない。カードは「未判定」（None）にする。
- vCenter・対象の名前・対象の moid の絞り込みは、ほかのイベントと同じ条件（`_event_filters` の期間以外）を使う。
- 一覧の印は期間全体の行に付く。カードは窓（起点まで）の行だけから作る。この違いをユーザーガイドに書く。

### 読み方

- 今の一覧の SELECT（`notable_score >= min_score`）は変えない。ここで読んだ行のうち、種別が定義にあるものに印を付ける。
- 最小スコアに届かない構成変更は、別の SELECT で読む。条件は「窓の中」「種別が定義にある」「`notable_score < min_score`」で、新しい順に `CONFIG_CHANGE_MAX_ROWS`（2,000）+ 1 行まで読む。
  - 上限を超えたら、新しい 2,000 行だけを使い、`config_changes_truncated` を真にする。ビュー全体を 422 にはしない。構成変更を足したことで、今まで出ていたビューが 422 にならないようにするためである。
  - 2 つの SELECT の間にスコアの再計算が確定すると、同じ行が両方に入ることがある（PostgreSQL の READ COMMITTED は文ごとにスナップショットを取る）。SELECT の直後、まとめる前に、足した行からイベントの id の重複を除く（今の SELECT の行を残す）。
- 両方の SELECT で `user_name` と `chain_id`、`collector_id` も読む。`TimelineEntry` には内部の項目として持たせ、`to_item` では出さない。
- `message` は読まない。返す項目の分だけ後から引く（`_event_messages`）。
- 別の SELECT で読んだ行を、以下「足した行」と呼ぶ。

### 足した行の扱い（今の一覧を変えない）

足した行が、今まで出ていた行の見え方を変えないようにする。そのため、足した行は今の行と別に処理し、最後に合わせる。

1. **今の行:** 今と同じく `merge_consecutive` でまとめ、`select_within_limit` で `item_limit` 件に絞る。足した行は入れない。
   - これで、足した行が今の行のまとめを分けることも、0 点と 10 点の同じ種別の行が 1 行にまとまることも、打ち切りで今の行が押し出されることも起きない。
   - 「影響の大きい対象」「新しい種別」「最初の兆候」は、今の行だけから作る。俯瞰の件数も変えない（`event_total` にはもともと入っている）。
2. **足した行:** 足した行どうしだけで `merge_consecutive` をかける。そのうえで、窓の終わりに近い順に `min(CONFIG_CHANGE_ITEM_LIMIT, item_limit)` 件まで残す（`CONFIG_CHANGE_ITEM_LIMIT` は 50）。近さは、まとめた行の `end_utc`（無ければ `timestamp_utc`）と窓の終わりの差で測る。この枠は `item_limit` の外にある。`item_limit` を小さくした利用者に、それより多い構成変更の行を見せないため、`item_limit` でも抑える。
3. **合わせる:** 1 と 2 を時刻順に並べて `items` にする。
   - `total_items` と `truncated` は、今の行だけで決める（意味を変えない）。足した行の打ち切りで「期間や対象を絞ってください」の注記（`TimelinePanel.tsx:142,262`）や報告書の「打ち切り: あり」が出ると、最小スコアでは絞れない行のために絞り込みを促すことになるためである。
   - 足した行は、結果に別の項目で返す。`config_change_items_total: int = 0`（まとめた後の足した行の数）、`config_change_items_shown: int = 0`（一覧に入れた足した行の数）、`config_change_items_truncated: bool = False`（枠で打ち切ったか）。画面と報告書は、今の行の数を `len(items) - config_change_items_shown` で求める（PR B で決めた）。画面は打ち切ったとき、「構成変更の行は、起点（または期間の終わり）に近い N 件だけを一覧に出しています」と別の注記を出す。
   - 一覧は最大で `item_limit` の 2 倍（`item_limit` が 50 を超えれば `item_limit` + 50）件になる。

足した行は、構成変更のカードの材料にもなる。カードは打ち切りの前の行から作るので、一覧から落ちてもカードには残る。

### 行の印

- `IncidentTimelineViewItem` に `config_change_kind: str | None = None` を足す。構成変更の行なら種類（`vm_reconfigure` など）、それ以外は None にする。最小スコア以上で読んだ行にも付ける。
- まとめた行は、最初の行の値を使う。`merge_key` は種別を含むので、種類の違う行はまとまらない。

### ハイライトのカード

`IncidentTimelineHighlights` に次を足す。

- `config_changes: list[IncidentTimelineConfigChange] | None = None`。None は「判定していない」を表す。足す前に保存した結果と、種別に `event` が無いときがこれにあたる。判定して 0 件なら空の配列にする。
- `config_changes_total: int = 0`（まとめた後の件数）
- `config_change_counts: dict[str, int] = {}`（種類ごとの、まとめた後の件数）
- `config_changes_truncated: bool = False`

`IncidentTimelineConfigChange` は次の項目を持つ。

| 項目 | 内容 |
|---|---|
| `kind`・`label` | 種類と表示名 |
| `first_utc`・`last_utc` | まとめた行の最初と最後の時刻 |
| `vcenter_id`・`vcenter_name` | vCenter |
| `entity_name`・`entity_moid`・`entity_type` | 対象（最初に対象を持つ行の値） |
| `user_names` | 変更した利用者（重複を除き、出た順に最大 3 人） |
| `event_types` | まとめた行の種別（重複を除き、最大 5 つ） |
| `event_count` | まとめた行の数 |
| `event_ids` | まとめた行のイベントの id（時刻順に最大 20） |

まとめ方:
- 材料は、窓の中の構成変更の行である（最小スコア以上の行と、足した行の両方）。`merge_consecutive` の前の、1 行ずつの行を使う。まとめた後の行は最初の id しか持たないためである。
- 行を時刻の順に見て、次の順に、すでにある組に入れる。どれにも当たらなければ新しい組にする。
  1. **chain:** 組み込みのコレクタ（`builtin.vcenter.events`・`builtin.vcenter.tasks`）の行で、種類・vCenter・`chain_id` が同じ組がある。種類が違う行は、同じ chain でも別の組にする（`upgradeVirtualHardware` のタスクの chain に `VmReconfiguredEvent` が入る場合など）。組の種類は 1 つに決まる。タスクとそのタスクから生まれたイベントは同じ chain なので、対象が違っても 1 件になる（`ClusterComputeResource.addHost` のタスクの対象はクラスタ、`HostAddedEvent` の対象はホスト、など）。プラグインの行は、`chain_id` の番号の空間が同じとは限らないので使わない。
  2. **対象:** 種類・vCenter・対象が同じで、その組の最後の行との間隔が 5 分以内の組がある。組の対象は、組の行のどれかが持つ対象とする（chain で作った組は、クラスタとホストのように対象を複数持つことがある）。対象は、両方に moid があれば moid で、無ければ名前で比べる。ホストが出す `esx.audit.maintenancemode.entered`（chain に入らない）と、vCenter が出す `EnteredMaintenanceModeEvent` がこれで 1 件になる。
  3. **対象なし:** 行も組も対象を持たないときは、種類・vCenter・利用者が同じで、その組の最後の行との間隔が 5 分以内の組に入れる。利用者が無い（None）行は、この規則ではまとめない。ロールの変更（`RoleAddedEvent` と `AuthorizationManager.addRole`）は、対象を持たないことがあるためである。
- 「組の最後の行との間隔」は、同じ組の行どうしで見る。間に別の対象の行が挟まっても、組は分かれない。
- 対象の規則で候補の組が複数あるときは、moid が一致する組を先に選ぶ。無ければ、名前で一致する組のうち最後の行が最も新しい組を選ぶ（PR B で決めた）。
- 2,000 行の上限で足した行を打ち切ったときは、カードの材料（最小スコア以上の行も含む）を、足した行の最も古い時刻以降に揃える。カードが一様な期間を表すようにするためである（PR B で決めた）。
- 長いタスク（メンテナンスモードに入るのに 30 分かかるなど）では、開始のイベント（`EnteringMaintenanceModeEvent`）がタスクと同じ chain なら 1 件に、違えば 2 件になる。どちらでも最初と最後の時刻が見える。

並べ方と上限:
- 新しい順（最後の時刻の降順）に、最大 20 件を返す。障害の直前の変更が先頭に来る。
- バックアップの製品の VM の再構成が続くと、ほかの種類が上限の外に出る。そのため、`config_change_counts` で種類ごとの件数を返す。画面はそれをカードの上に出す。
- `config_changes_total` には、まとめた後の全件数を入れる。

### 出力（案 10）

- 報告書（`report.md`）のハイライトに「### 構成変更」の節を足す。
  - 1 件ごとに、時刻、表示名、対象、vCenter、利用者、件数を書く。無害化の規則は、ほかの節と同じにする。
  - 種類ごとの件数、上限を超えた件数、`config_changes_truncated` も書く。
  - `config_changes` が None なら「判定していません（この機能の前に保存した結果、または種別にイベントが無い）」と書く。
- `items.csv` に `config_change_kind` の列を足す（`_ITEM_COLUMNS`）。
- `result.json` は、足した項目がそのまま入る。

### 利用者名の扱い

`user_names` は個人の情報である。出る場所は次のとおり。
- **画面:** タイムラインのカード。viewer も見られる（イベントの一覧の `user_name` と同じ）。
- **出力:** 報告書と `result.json`。PR B で出るようになるので、ユーザーガイドの「外部に渡すときの確認」（`docs/userguide/timeline.md:206`）と CHANGELOG に、利用者名が入ることを PR B で書く。
- **保存した結果:** 手動で保存したスナップショットの `result_payload` にも入る。スナップショットの API で viewer も読める。イベントの保持期間（7 日）を過ぎても、スナップショットの結果の保持期間（既定で 90 日）のあいだは残る。ユーザーガイドの「外部に渡すときの確認」と同じ節に、このことも書く。
- **LLM:** 渡さない。チャットに渡すタイムラインは、ビューのハイライトを使わない（1 章）。

### モックとシード

- スクリーンショット用のシード（`dev/screenshot_e2e_seed.py`）に、障害の前の構成変更を足す。テスト（`tests/test_screenshot_e2e_seed.py`）も合わせる。
  - `demo-esxi-01` のメンテナンスモード（入って、出る）
  - `demo-vm-01` の再構成。イベントとタスクの 2 行を、同じ利用者・同じ `chain_id` で入れる。
- モックのコレクタ（`mocks/mock_collectors.py`）にも、構成変更のイベントとタスクをときどき出す。

## 4. 画面（PR C）

- **カード:** ハイライトに「構成変更」のカードを足す。置き場所は、検知した障害パターンのカードの隣にする。
  - 上に、種類ごとの件数（`config_change_counts`）を出す。
  - 1 件ごとに、次のものを出す。
    - 表示名
    - 対象と vCenter
    - 利用者
    - 時刻（最初と最後が違えば範囲）
    - 件数
  - 操作は 3 つ。
    - 「ここを起点にする」: 最後の時刻（`last_utc`）を起点にする。窓は起点ちょうどの行を含むので、押した変更はカードに残る。
    - 「この対象で絞る」: moid があれば moid で、無ければ名前で絞る。対象が無ければ出さない。
    - 一覧の行へ移動する: `event_ids` のうち、一覧の行の id（`event:<id>`）として `listedIds` に最初に見つかるものへ移動する。見つからなければ出さない。
  - 上限を超えたら、総数と「新しい 20 件を表示しています」を出す。`config_changes_truncated` が真なら、「古い構成変更は省きました」を出す。
  - 空の配列なら、「この期間に構成変更はありません」（起点があれば「起点までに」）と出す。None なら「判定していません」と出す（パターンのカードと同じ考え方）。種別に `event` が無ければ、カードを出さない。
- **足した行の注記:** `config_change_items_truncated` が真なら、「構成変更の行は、起点（または期間の終わり）に近い N 件だけを一覧に出しています」と出す（N は `config_change_items_shown`）。
- **行の印:** 時系列の一覧の行に、「構成変更」の印（バッジ）を付ける。色はトークンを使い、ダークモードで確かめる。印の名前（`aria-label` など）でも、スクリーンリーダーに伝わるようにする。
- **スキーマ:** zod に、足した項目を既定値付きで足す。
  - `config_change_kind`: `.nullable().optional()`
  - `config_changes`: `.nullable().optional()`
  - `config_changes_total`: `.default(0)`
  - `config_change_counts`: `.default({})`
  - `config_changes_truncated`: `.default(false)`
- **文言:** 最小スコアの説明が「イベントはスコアがこの値以上のものだけを一覧に出す」のままだと誤りになる。次を直す。
  - `TimelineConditionBar.tsx:247`
  - アプリ内ヘルプのハイライトの説明（`frontend/src/help/tabHelpContent.ts:57`）。構成変更のカードを足す。
  - `docs/userguide/timeline.md` の最小スコアの行（74 行）と「最小スコアで絞る」（291 行）
- **文書:**
  - `docs/userguide/timeline.md` に「構成変更」の節を足す。次のことを書く。
    - 対象の種類（2 章の表を短くしたもの）
    - 最小スコアに関係なく出ること
    - 一覧の枠（50 件）
    - 一覧の印は期間全体、カードは起点まで
    - 「起点に最も近い」の印（`timelineModel.ts:81`）は一覧の全行から選ぶので、構成変更の行に付くことがある
    - カードのまとめ方
  - 同じファイルの「一覧に残す行と注記」とハイライトの表（95-100 行）も直す。
  - CHANGELOG を更新する。
  - 10 案の計画書の進み具合を直す。
  - `docs/features/config-change-detection.md` の冒頭の「予定」の注記を外し、画面の表示に合わせて直す。
- **ドキュメント用の画像:** `docs/images/timeline.png` は、俯瞰のグラフの位置から撮る。カードが写る位置まで入るかを撮って確かめ、写るなら撮り直す。（PR C で撮って確かめた。カードは写る範囲より下にあるので、撮り直さない）

## 5. PR の分け方

### PR A: 本書

本書だけ。

### PR B: 構成変更の定義と API

- `rules/config_changes.py`（定義）とテスト。
  - 種別が 2 つの種類に入らないこと。
  - タスクの種別が 512 文字以内に収まること。
- `services/incident_timeline_view.py`:
  - 構成変更の SELECT
  - 足した行の扱い
  - 行の印
  - カードのまとめ方
- スキーマ（3 章の項目。すべて既定値付き）。
- 出力（報告書の節、`items.csv` の列）。
- モックとシード。
- ユーザーガイドの「外部に渡すときの確認」に利用者名を足すこと。CHANGELOG。
- `docs/features/config-change-detection.md` を実装に合わせて直す。タスクの操作名の確認（8 章）の結果も反映する。
- 画面の件数の文言（`TimelinePanel.tsx` の「N 件中 M 件」「N 件の出来事」）を、今の行の数（`len(items) - config_change_items_shown`）で出す。PR B だけをマージしても、件数が合わなくならないようにするための最小限の変更である。足した行の注記・カード・行の印は PR C で作る。
- テスト（`tests/test_incident_timeline_config_changes.py`。PostgreSQL でも流すテストは、名前に `postgres` と `config_change` を含め、`.github/workflows/ci.yml` の `-k` の条件に `config_change` を足す）:
  - 0 点の構成変更が、一覧とカードに出ること。最小スコア以上の構成変更にも印が付くこと。
  - 起点より後の、最小スコアに届かない構成変更は出ないこと。起点ちょうど（マイクロ秒の端数あり）の行は出ること。
  - 足した行が、「新しい種別」と「影響の大きい対象」と俯瞰の件数に入らないこと。
  - **今の一覧を変えないこと:**
    - 起点あり・構成変更が大量・起点の後ろに error が 1 行あるとき、error の行が一覧に残ること。
    - 起点なし・エラーのログが大量にあるとき、ログの行数が足す前と同じであること。
    - 構成変更の行が間に入っても、今の行のまとめ（ログの行数、`top_entities`）が足す前と同じであること。
    - 同じ種別の 0 点と 10 点の行が、1 行にまとまらないこと。
  - 足した行が一覧に最大 `min(50, item_limit)` 件入ること。足した行だけを打ち切ったとき、`truncated` は偽のまま、`config_change_items_truncated` が真になること。`total_items` が足す前と同じであること。
  - 構成変更の行が 2,001 行あっても 422 にならず、`config_changes_truncated` が真になること。
  - 2 つの SELECT に同じ id が入っても、一覧に重複が出ないこと。
  - まとめ方:
    - 同じ chain のイベントとタスクが、対象が違っても 1 件になること。プラグインの行は chain で結ばないこと。
    - chain の無い同じ種類・同じ対象の行が、5 分以内なら 1 件、超えたら別になること。
    - 別の対象の行が間に挟まっても、組が分かれないこと。
    - 対象の無いロールの変更のイベントとタスクが、利用者で 1 件になること。利用者が None の行は、この規則でまとまらないこと。
    - chain で作った組（クラスタとホスト）に、ホストを対象とする chain の無い行が 5 分以内に来たら、同じ組に入ること。
    - 同じ chain でも種類が違う行は、別の組になること。
    - 種類・vCenter が違えばまとまらないこと。
    - `config_change_counts` と `config_changes_total` が合うこと。
  - 対象と vCenter の絞り込みが効くこと。種別に `event` が無ければ `config_changes` が None になること。
  - 一覧の打ち切りで落ちた行も、カードに残ること。
  - 足す前の形で保存したスナップショットの結果が読めること（`has_result` が真のまま、`config_changes` が None、出力もできること）。
  - 出力の報告書に節が入り（None の注記を含む）、`items.csv` に列が入ること。

### PR C: 画面と文書

4 章のとおり。スクリーンショットを PR に添える。

各 PR は origin/main から作ったブランチで進める。実装は Codex（gpt-6.2-sol）に任せ、critic がレビューする。全体のテストは Claude 側で流す。

## 6. 確認方法

- バックエンド: `uv run pytest`（PostgreSQL を含む）、`mypy`、`ruff`。
- 画面: `vitest`、`tsc`、`eslint`。
- スクリーンショット用のシードで、カードと行の印を撮る（ライトとダーク）。
- タスクの操作名の確認（8 章）。PR B のマージの前に行い、結果を 2 章の表に反映する。

## 7. 範囲外（後続）

- 設定の値の差分（何から何に変えたか）: 案 2b。
- 構成変更の一覧を、設定の画面で編集すること。
- 俯瞰のグラフに、構成変更の帯を出すこと。
- チャット（LLM）に構成変更を渡すこと。渡すなら、利用者名の匿名化を先に決める。
- 構成変更の種類の追加（vSAN、NSX、証明書、スナップショットの復元など）。

## 8. リスク

- **タスクの操作名の形と、履歴に残るか:** 2 つのことを確かめていない。
  - vcsim のタスクは `VirtualMachine.reconfigVm` の形で、本書の一覧（`VirtualMachine.reconfigure`）と合わない。本書は、タスクの説明の一覧の形が実機の `descriptionId` だとみなす。この経路は、vcsim では通しで確かめられない。既存のテストの形（`VirtualMachine.powerOn`）は本プロジェクトが書いたモックなので、根拠にならない。
  - 69 種類のうち、`addRole`・`setEntityPermissions`・`OptionManager.updateValues`・`NetworkSystem.update*`・`FirewallSystem.*`・`DateTimeSystem.updateConfig` などは同期のメソッドである。そもそもタスクの履歴に残るかが分からない。
  - 外れていたら、そのタスクは照合されず、イベントだけが出る。カードと行の印は、イベントの分は正しく出る。
  - **確かめ方:** PR B のマージの前に、利用者の許可を得て、次の順で行う。
    1. vCenter に触れずに、タスクのコレクタが動いている環境の DB で `SELECT DISTINCT event_type FROM events WHERE event_type LIKE 'task.success.%'` を流す。
    2. 足りなければ、実機の vCenter の最近のタスクの `descriptionId` を、読み取りだけで一覧にする。
    3. 結果を 2 章の表に反映する（出ない操作は外すか、注記する）。
  - **確かめた結果（2026-11-24、利用者の許可を得て読み取りだけで実施）:**
    - 開発環境の DB（`main` の PR #367 の時点のもの）は、タスクのコレクタ（PR #370）より前なので、`task.*` の行が無かった。
    - 実機の vCenter のタスクの履歴は 10 件だけだった（期間を指定しなくても同じ）。構成変更の操作は無かった。現れた `descriptionId` は次の 4 種類で、どれもタスクの説明の一覧の形と完全に一致した。
      - `com.vmware.vcIntegrity.lifecycle.ScheduledHclValidationTask`
      - `com.vmware.vcIntegrity.SigUpdateTask`
      - `Datacenter.ExecuteVmPowerOnLRO`
      - `Datacenter.powerOnVm`
      - vcsim の形（Go の関数名から作る）とは違い、本書の前提を支える。
    - DB の構成変更のイベントは、`VmReconfiguredEvent` の 3 件だけだった（約 3 万 2 千件のうち）。3 件とも `chain_id` と利用者を持ち、同じ `chain_id` のタスクの開始イベント（`vim.event.TaskEvent`）があった。開始イベントのメッセージは 3 件とも、説明の一覧の `VirtualMachine.reconfigure` の表示名（Reconfigure virtual machine）を含んでいた。タスクの `eventChainId` は開始イベントの `chainId` と同じなので、VM の再構成のイベントとタスクは chain で 1 件にまとまる。
    - 確かめられなかったこと: `VirtualMachine.reconfigure` 以外の操作の名前と、同期のメソッドがタスクの履歴に残るか。表は変えず、このリスクを残す。
- **件数:** VM の再構成を頻繁に行う製品（バックアップや監視のツールなど）がある環境では、構成変更の行が多くなる。
  - 2,000 行を超えたら、新しいものだけを使う。ビューは 422 にならない。
  - 一覧に入る足した行は 50 件までで、今の行の枠は使わない。
  - カードは新しい 20 件だけを出すが、種類ごとの件数を出すので、ほかの種類があることは分かる。
- **ホストのアップグレードの検出:** `com.vmware.vcIntegrity.*` は Update Manager（ベースライン）のイベントである。イメージで管理する vLCM のクラスタでも出るかは確かめていない。ユーザーガイドでは「Update Manager による」と限定して書く。
- **起動時に出る esx.audit:** `esx.audit.ssh.enabled`・`shell.enabled`・`dcui.enabled` は、設定によってはホストの起動時にも出る。障害でホストが再起動した後に「変更」に見えることがある。ユーザーガイドに書く。
- **まとめ方の誤り:**
  - 同じ対象の同じ種類の変更が 5 分以内に続くと、別の人の別の変更でも 1 件になる。利用者は最大 3 人まで並べ、件数も出すので、まとまったことは分かる。
  - chain が結べず、対象も違う組（プラグインのイベントなど）は、2 件に分かれる。
- **保存した結果:** 足す項目に既定値が無いと、保存済みの結果が読めなくなる。テストで、足す前の形の結果を読む。足す前の結果は `config_changes` が None になり、「判定していません」と出る。
