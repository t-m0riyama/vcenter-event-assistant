# 構成の差分を記録する

最終更新: 2026-11-26（PR A マージ済み。PR B を実装中）

[障害調査を楽にする機能 10 案](2026-11-22-troubleshooting-ideas.md)（以下「10 案」）の「案 2b」（構成変更の追跡の第 2 段）にあたる。ESXi のビルド、クラスタの HA・DRS の設定、標準 vSwitch とポートグループ、VM の構成を定期的に読み、値が変わったときに「何から何に変わったか」を記録する。記録した差分は、タイムラインの対象の欄と、案 2a の「構成変更」のカードに出す。Issue は起票していない。

コードの場所は、バックエンドを `src/vcenter_event_assistant/` から、画面を `frontend/src/` から書く。行番号は、本書を書いた時点の origin/main（46f78bc）のものである。

## 進捗

| PR | 内容 | 状態 |
|---|---|---|
| A | 本書 | マージ済み（[PR #395](https://github.com/t-m0riyama/vcenter-event-assistant/pull/395)） |
| B | 構成の読み取り、保存、差分の記録（実機の確認の道具を含む） | マージ済み（[PR #396](https://github.com/t-m0riyama/vcenter-event-assistant/pull/396)） |
| C | API（差分の一覧、カードへの差分の添付、出力、収集の状態）とシード | 実装中 |
| D | 画面（タイムラインの対象の欄、カード、設定の収集の状態）と文書 | 未着手 |

各 PR は単独でマージでき、テストが通る状態にする。

## Context

案 2a で、構成変更のイベントとタスク（VM の再構成、クラスタの設定の変更など）をタイムラインで目立たせた。ただし、イベントから分かるのは「変えた」という事実と利用者だけで、何から何に変えたかは分からない。たとえば `VmReconfiguredEvent` だけでは、CPU を減らしたのか、NIC のポートグループを替えたのかが分からない。また、ESXi を直接操作した変更や、イベントに残らない変更は、案 2a では見えない。

そこで、構成そのものを定期的に読み、前回の値と比べて差分を記録する。案 1（影響範囲マップ、[計画書](2026-11-23-impact-map.md)）の関係の収集の上に作る。

決めたこと（利用者の決定）:
- **記録する構成:** ESXi のビルドとクラスタの HA・DRS の設定、標準 vSwitch とポートグループ、VM の構成。マルチパスのポリシーと分散スイッチは後続にする。
- **保持期間:** 差分は、イベントとは別の設定で保持する。既定は 30 日とする。
- **見せ方:** タイムラインで対象を moid で絞ったときに、影響範囲の隣に「構成の差分」の欄を出す。案 2a の構成変更のカードにも、その時刻の差分を添える。API も用意する。
- **実機での確認:** Claude が読み取り専用の確認の道具を用意し、利用者が登録済みの vCenter で実行して出力を貼る。Claude は実機に接続しない。

## 1. 前提（コードで確かめたこと）

- **関係の収集（案 1）:** `services/inventory.py` の `sync_inventory`（316 行）が、有効な vCenter を順に処理する（`_sync_enabled_vcenters`、327 行）。
  - 読み取りは、専用のデーモンスレッドで `read_vcenter_inventory`（83 行）が接続から切断までを行う。接続の `http_connection_timeout` は `inventory_sync_timeout_seconds`（`settings.py:58`、既定 300）である。
  - 非同期の側は `_read_with_timeout`（274 行）で、同じ秒数だけ `Future` を待つ。タイムアウトしてもスレッドは止まらない。前回のスレッドが終わっていない vCenter は飛ばし、同時に動くスレッドは `_WORKER_COUNT`（2）までである。
  - 観測の時刻は、`_sync_enabled_vcenters` が読み取りの後に `utcnow()` で取る。保存は `persist_inventory`（111 行）が 1 つのトランザクションで行い、`t = max(観測の時刻, last_success_at)` にそろえる。`instance_uuid` が前回と違えば、記録をやり直す（関数の中の `reset`）。
  - 失敗は `_record_failure`（243 行）が別のトランザクションで `inventory_sync_states` に残す。
  - モックのモードでは `mocks/mock_inventory.py` の `mock_inventory` が観測を返す。シード（`dev/screenshot_e2e_seed.py`）も同じ定義を使う。
- **読み取りの関数:** `collectors/inventory.py` の `read_inventory`（61 行）。rootFolder の再帰の ContainerView と `RetrievePropertiesEx`（`maxObjects=1000`）で読み、`token` が尽きるまで `ContinueRetrievePropertiesEx` で続ける。例外のときは `CancelRetrievePropertiesEx` を呼び、View は `finally` で `Destroy()` する。参照からは `_moId` と `_wsdlName` だけを読む。テンプレートの VM（`summary.config.template` が真）は除く。
- **収集の状態:** `InventorySyncState`（`db/models.py:137`）に、最後の成功・失敗・警告と件数がある。`GET /api/inventory/status`（`api/routes/inventory.py`）が viewer にも返す。
- **保持期間の削除:** `jobs/scheduler.py:126` の `purge_retention` から `purge_old_inventory`（`services/inventory.py:360`）を呼ぶ。関係・管理対象・観測の記録は `event_retention_days`（既定 7 日）で消える。
- **案 2a のカード:** `services/incident_timeline_view.py` の `_summarize_config_changes`（1079 行）が、構成変更の行を chain・対象・利用者でまとめ、`IncidentTimelineConfigChange`（`api/schemas/incident_timeline_view.py:227`）を作る。組（`_ConfigChangeGroup`）は対象を 1 つ（`target`）しか持たず、組の行の moid の集まりは残していない。カードは `IncidentTimelineHighlights.config_changes`（284 行）に入り、最大 20 枚である。足す項目には既定値が要る。保存したスナップショットの結果（`result_payload`）は、今のスキーマで読めなければ None になるためである（案 2a の計画書の 1 章）。
- **出力（案 10）:** 報告書のカードの節は `services/incident_timeline_export.py:345` の `_config_changes_highlight` で作る。報告書には匿名化の仕組みは無い。
- **チャット:** チャットに渡すタイムライン（`build_chat_incident_timeline`）は、ハイライトと構成変更のカードを使わない。カードに差分を足しても、LLM には渡らない。
- **影響範囲の欄（案 1 の PR D）:** `panels/timeline/TimelineImpactSection.tsx`。タイムラインで対象を moid で絞ったときだけ出る。
- **移行:** head は `e4f5a6b7c8d9`（案 9 の PR C）。実装のときに origin/main で確かめ直す。
- **CI の PostgreSQL:** `.github/workflows/ci.yml:221-230` の手順が、ファイルと `-k "postgres and (… or inventory or …)"` で選んだテストだけを流す。新しいテストは、ファイルをここに足し、名前に `postgres` と、`-k` に入っているキーワード（新しく `config_diff` を足す）の両方を入れないと、PostgreSQL では流れない。

## 2. 記録する構成

### 読み方

関係の読み取りとは別の `RetrievePropertiesEx` で読む（以下「構成の読み取り」）。同じスレッドと同じ接続の中で、関係の読み取りの後に続けて行う。関係と構成の結果は、スレッドから別々に受け取る（3 章の「スレッドと時間」）。構成の読み取りが失敗しても遅れても、関係の記録は今までどおり残すためである。

構成の読み取りは 2 段で行う。

1. **概要（毎回すべて）:** 関係の読み取りと同じ ContainerView の作り方で、次の属性を読む。

   | 型 | 読む属性 |
   |---|---|
   | `HostSystem` | `name`・`runtime.connectionState`・`summary.config.product`・`config.network.vswitch`・`config.network.portgroup` |
   | `ClusterComputeResource` | `name`・`configuration.dasConfig`・`configuration.drsConfig`（下の「パスの代わり」） |
   | `VirtualMachine` | `name`・`runtime.connectionState`・`summary.config.template`・`config.changeVersion` |

2. **VM の詳細（読む必要のある VM だけ）:** 接続している（`runtime.connectionState` が `connected`）VM で、`config.changeVersion` が段 1 で読めたもののうち、次のどれかに当たる VM だけを、下の順で読む。読み残しが出たときに、古いものから片付けるためである。
   1. 保存した行の正規化の版（`format`）が今の版と違う VM
   2. `config.changeVersion` が保存した値と違う VM
   3. 保存した行が無い VM

   群の中は、保存した行の `verified_at` の古い順（同じなら moid の順）に読む。行の無い VM は moid の順にする。毎晩のスナップショットのように、1 回で読める数より多くの VM が変わっても、同じ VM がいつまでも読み残しにならないようにするためである。接続していない VM と、`config.changeVersion` が読めなかった VM は段 2 で読まず、3 章のとおり持ち越す。

   段 2 で必ず要る属性は `config.changeVersion`・`config.hardware.numCPU`・`config.hardware.memoryMB`・`config.hardware.device` だけとし、ほかの属性が `propSet` に無い（未設定）ときは、その項目を None にして比べる。必ず要る属性が欠けた VM と、どの属性でも `missingSet` に入った（権限や一時的な障害で読めなかった）VM は「段 2 で読めなかった VM」として持ち越し、その数を `config_deferred_count` とは別に警告に残す。段 1 と段 2 の間に削除されて `ManagedObjectNotFound` で外した VM も持ち越すが、警告の数には入れない。ディスクの元の backing が分からない（循環、`parent` が読めない、深さ 64 を超える）VM も、段 2 で読めなかった VM として持ち越す。

   ContainerView を使わず、段 1 で受け取った VM の参照（moid から作り直さない）を並べた `ObjectSpec`（`skip=False`、`selectSet` なし）で、200 台ずつ読む。読む属性は `config.changeVersion`・`config.hardware.numCPU`・`config.hardware.numCoresPerSocket`・`config.hardware.memoryMB`・`config.version`・`config.guestId`・`config.cpuAllocation`・`config.memoryAllocation`・`config.hardware.device` である。保存する `change_version` には、段 2 で読んだ値を使う（段 1 と段 2 の間に変わることがあるため）。

   段 1 と段 2 の間に VM が削除されると、組の要求全体が `ManagedObjectNotFound` で失敗することがある。そのときは、例外の `obj` の VM を組から外して、同じ組を読み直す（1 つの組で最大 10 回まで。超えたら構成の読み取りの失敗にする）。外した VM は、段 2 では読めなかった VM として扱う（3 章）。この例外の出方は、7 章の道具でも確かめる。

`config.hardware.device` を含む段 2 の属性は、VM 1 台で 10 KB を超える（登録済みの vCenter で 21 台・265 KB、1 台あたり約 12.6 KB。vcsim では装置 13 個・4,086 バイト）。VM 5,000 台なら毎回 60 MB 前後になるので、毎回は読まない。`config.changeVersion` は VM の構成が変わるたびに変わる値で、これを先に読めば、変わった VM だけを読める。

**パスの代わり:** クラスタは、古い `configuration.dasConfig`・`configuration.drsConfig`（`ClusterConfigInfo`）を先に使う。登録済みの vCenter（8.0.3）は、部分型を経る `configurationEx.dasConfig` を `vmodl.query.InvalidProperty` で拒んだためである（2026-11-26、下の「確かめた結果（実機）」）。段 1 の要求が `InvalidProperty` で失敗したら、`configurationEx.dasConfig`・`configurationEx.drsConfig` に替えて、段 1 を 1 回だけ読み直す。古いパスを除いた版の vCenter に備えるためである。読み直しで成功したら、その vCenter ではプロセスが終わるまで新しいパスを使う（vCenter ごとの記憶をプロセスの中に持つ）。記憶は複数の読み取りのスレッドから読み書きされるので、`threading.Lock` で守る。新しいパスでも失敗したら、構成の読み取りの失敗にする。

### 確かめた結果（実機）

利用者が、登録済みの vCenter（8.0.3、ホスト 1 台・クラスタ 1・VM 21 台）で 7 章の道具を実行した（2026-11-26）。

- **段 1 のパス:** ホストと VM のパスは、すべて値が返った。クラスタの `configurationEx.dasConfig`・`configurationEx.drsConfig` は `vmodl.query.InvalidProperty` で拒まれ、古い `configuration.dasConfig`・`configuration.drsConfig` は値が返った。そのため、古いパスを先に使う（上の「パスの代わり」）。
- **段 2 のパス:** 9 つの属性が、21 台すべてで返った。
- **欠けた値:** `missingSet` に入った属性、`propSet` に無い属性、空の配列は、段 1・段 2 とも 0 件だった。
- **時間と量:**
  - 段 1 は 0.16〜0.18 秒で、約 13 KB だった（クラスタ 1,831 バイト、ホスト 8,189 バイト、VM 3,026 バイト）。
  - 段 2 は全 21 台で 0.06〜0.08 秒、265,159 バイトだった。
  - `ManagedObjectNotFound` は出なかった。
- **偽の差分:** 構成を変えずに 300 秒空けて 2 回読み、正規化した値の差分は 0 件、`config.changeVersion` が変わった VM も 0 台だった。
- **ディスク:** 42 台のディスクのすべてで、元の backing に `uuid` があった。スナップショットの差分ディスクは 4 台あった。その 4 台とも、今の backing と元の backing で `thin` も `uuid` も同じだった（`disks_with_different_thin=0`・`disks_with_different_uuid=0`）。
- **見つかった不具合:** 最初の実行では、すべてのパスが `AttributeError` で失敗した。`pathSet` にタプルを渡していたため、pyVmomi が要求を組み立てられなかった。案 1 の関係の収集（`collectors/inventory.py`）にも同じ誤りがあり、PR #399 で直した。どちらにも、要求を `SoapAdapter.Serialize` で直列化するテストを足した。

### 確かめた結果（vcsim）

vcsim（既定の環境）で、次を確かめた（2026-11-26）。

- 上の表のパスは、すべてエラーにならずに値が返った。`missingSet` も無かった。
  - `configurationEx` の宣言の型は `ComputeResourceConfigInfo` で、`dasConfig`・`drsConfig` は部分型の `ClusterConfigInfoEx` にしか無い。それでも、vcsim では `configurationEx.dasConfig` のパスで値が返った。古い `configuration.dasConfig`・`configuration.drsConfig` も値が返った。
  - `summary.config.product` と `config.product` は、どちらも `AboutInfo` で返った。
- VM の構成を変えると（`ReconfigVM_Task` で CPU を 1 から 2 に）、`config.changeVersion` が変わった。
- 構成を変えなくても変わる値があった。比べる項目から外す（下の「比べる項目」）。
  - `HostPortGroup.port`: 使っているポートの一覧。VM の電源を入れると増える（`Management Network` は 1 件、`VM Network` は 0 件だった）。
  - `HostVirtualSwitch.numPortsAvailable`: 空いているポートの数。同じ理由で変わる。
- 途中が未設定のパス（`configurationEx.dasConfig.admissionControlPolicy` など）は、`missingSet` にも入らずに `propSet` から消えた（critic のレビューで確かめた）。属性が `propSet` に無い場合の扱いを、3 章で決める。
- vcsim のクラスタの `dasConfig` は、項目がすべて None だった（HA を設定していない）。
- vcsim の装置のラベルは `disk-202-0`・`ethernet-0` の形で、実機の `Hard disk 1` と違う。装置は、ラベルではなく `key` で見分ける（下の表）。

### 比べる項目

構成は、読んだ値をそのまま比べない。次の表の項目だけを取り出して正規化し、正規化した値どうしを比べる。表に無い項目は比べない。読んだ値には、構成を変えなくても変わる項目や、並び順が変わる配列があり、そのまま比べると、毎回の観測で差分が出るためである。

正規化の規則:
- 値は、数値・文字列・真偽・None と、それらの配列と辞書だけにする。pyVmomi の列挙は文字列にする。
- 要素の集まりは、表の「キー」を文字列にして辞書にする。vSwitch とポートグループは名前を、ディスクと NIC は装置の `key`（ディスクは 2000 番台、NIC は 4000 番台）を使う。`key` は、装置が VM に付いている間は変わらないが、外した後は、後から足した別の装置に使い回されることがある（[vSphere Web Services API の `VirtualDevice`](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.vm.device.VirtualDevice.html)、Issue #397）。そこで、ディスクは下の「装置の入れ替わり」の規則で、同じ `key` の別の装置を見分ける。名前が重なったときは、そのうち 1 つだけを残して警告を記録する（ESXi では同じホストに同じ名前は作れないので、起きないはずである）。
- ディスクと NIC のラベル（`deviceInfo.label`）は、表示のための項目として値に入れる。ラベルが変わっても差分として記録する（`label` の項目）。
- 並び順に意味の無い配列（vSwitch のアップリンクの NIC、`failover_hosts`）は並べ替える。意味のある配列（アクティブ・スタンバイの NIC の順）は並べ替えない。
- 物理 NIC は、参照のキー（`key-vim.host.PhysicalNic-vmnic0`）から装置名（`vmnic0`）だけを取る。
- ポートグループの `spec.policy` の上書きは、項目ごとに見る。その項目を上書きしていなければ None にする。

| 種類（`category`） | 対象 | 元の属性 | 要素とキー | 項目 |
|---|---|---|---|---|
| `host_build` | ホスト | `summary.config.product` | なし | `version`・`build` |
| `host_vswitch` | ホスト | `config.network.vswitch[]` | `name` | `mtu`・`uplinks`（`pnic` の装置名、並べ替える）・`teaming_policy`（`spec.policy.nicTeaming.policy`）・`active_nics`・`standby_nics`（`spec.policy.nicTeaming.nicOrder`、順を保つ）・`allow_promiscuous`・`mac_changes`・`forged_transmits`（`spec.policy.security`） |
| `host_portgroup` | ホスト | `config.network.portgroup[]` | `spec.name` | `vlan_id`・`vswitch`（`spec.vswitchName`）と、上書きの `teaming_policy`・`active_nics`・`standby_nics`・`allow_promiscuous`・`mac_changes`・`forged_transmits` |
| `cluster_ha` | クラスタ | `configuration.dasConfig`（代わりに `configurationEx.dasConfig`） | なし | `enabled`・`host_monitoring`・`vm_monitoring`・`admission_control_enabled`・`admission_control_policy`・`failover_level`・`auto_compute`・`cpu_failover_percent`・`memory_failover_percent`・`failover_hosts`・`restart_priority`・`isolation_response`（下の注） |
| `cluster_drs` | クラスタ | `configuration.drsConfig`（代わりに `configurationEx.drsConfig`） | なし | `enabled`・`default_vm_behavior`・`vmotion_rate` |
| `vm_config` | VM | 段 2 の属性 | なし | `num_cpu`・`cores_per_socket`・`memory_mb`・`hardware_version`（`config.version`）・`guest_id`・`cpu_reservation_mhz`・`cpu_limit_mhz`・`cpu_shares`・`memory_reservation_mb`・`memory_limit_mb`・`memory_shares`（`shares.level`。`custom` のときだけ `custom:<shares>`） |
| （`vm_config` の中） | VM のディスク | `config.hardware.device` の `VirtualDisk` | `disk:<key>` | `label`・`uuid`・`capacity_kb`・`thin`（`thinProvisioned`）・`disk_mode`（`diskMode`）。`uuid`・`thin`・`disk_mode` は、`backing.parent` を最後までたどった元のディスクの backing から読む。`uuid` は前後の空白を除いて小文字にし、空文字と、`uuid` を持たない backing（`FlatVer1`・`SparseVer1`）では None |
| （`vm_config` の中） | VM の NIC | `config.hardware.device` の `VirtualEthernetCard` | `nic:<key>` | `label`・`adapter`（型名。例: `VirtualVmxnet3`）・`network`（標準のポートグループなら `backing.deviceName`、分散なら `backing.port.portgroupKey`、NSX なら `backing.opaqueNetworkId`、それ以外の backing なら None）・`start_connected`（`connectable.startConnected`）・`mac_address` |

装置の入れ替わり:
- 同じ `disk:<key>` で、前の値と今の値の `uuid` がどちらも None でなく、互いに違うときは、別のディスクに入れ替わったとみなす。項目ごとの差分は作らず、「要素が減った」行（前の値）と「要素が増えた」行（今の値）を、同じ観測で 1 行ずつ入れる。
- `uuid` が片方でも None なら、入れ替わりは判定せず、今までどおり項目ごとに比べる（`uuid` が None から値に、値から None に変わった差分も、項目の差分として記録する）。
- NIC は入れ替わりを判定しない。`mac_address` は項目として比べるだけにする。交換した NIC はふつう新しい MAC を受け取るので、その差分で気づける。ただし MAC は手で変えられるので、入れ替わりの判定には使わない。
- 見分けられないこと: 同じ `key` で `uuid` が同じ（または無い）ディスクの交換と、同じ `key` の NIC の交換は、項目の差分として記録されるか、項目がすべて同じなら何も記録されない。差分は「観測した項目の違い」であり、画面と報告書は、同じ装置が続いていたとも、差分が無いので交換も無かったとも言い切らない（4 章・5 章）。

`cluster_ha` の注:
- `admission_control_policy` は型名（`vim.cluster.FailoverLevelAdmissionControlPolicy` など）から、先頭の `vim.cluster.Failover` と末尾の `AdmissionControlPolicy` を除いたもの（`Level`・`Resources`・`Host`）にする。ポリシーが無ければ None。
- `failover_level` は `admissionControlPolicy.failoverLevel` を使う（`DasConfigInfo.failoverLevel` は使わない）。
- `auto_compute` は Resources のポリシーの `autoComputePercentages`。真のときの割合は、ホストの増減で自動で変わるので、`cpu_failover_percent`・`memory_failover_percent` を None にする。偽のときだけ、`cpuFailoverResourcesPercent`・`memoryFailoverResourcesPercent` を入れる。
- `failover_hosts` は Host のポリシーの `failoverHosts` の moid を並べ替えた配列。
- その型に無い項目は None にする。
- `restart_priority`・`isolation_response` は `defaultVmSettings` から取る。

外した項目と理由:
- `HostPortGroup.port`・`HostVirtualSwitch.numPortsAvailable`: 構成を変えなくても変わる（上の確認）。
- `HostVirtualSwitch.numPorts`: ESXi 5.5 からポートの数は自動で増減する。
- ディスクの `backing.fileName`: スナップショットを取るとデルタディスクに替わる。同じ理由で、`thin`・`disk_mode` は今の backing（差分ディスク。`SeSparseBackingInfo` は `thinProvisioned` を持たない）ではなく、`parent` をたどった元の backing から読む。データストアの移動は、案 1 の関係（`vm_datastore`）で分かる。
- NIC の `connectable.connected`: 電源の状態で変わる。
- `configurationEx` の残り（ルール、VM ごとの上書き、グループ）: 量が多く、最初の版では扱わない（8 章）。

### 値の形と差分の行の例

正規化した値（`value`）は、種類ごとに次の形の JSON にする。

```json
// host_build
{"version": "8.0.2", "build": "21997540"}

// host_vswitch（host_portgroup も同じ形で、キーがポートグループ名）
{"vSwitch0": {"mtu": 1500, "uplinks": ["vmnic0", "vmnic1"], "teaming_policy": "loadbalance_srcid",
              "active_nics": ["vmnic0"], "standby_nics": ["vmnic1"],
              "allow_promiscuous": false, "mac_changes": false, "forged_transmits": false}}

// vm_config
{"num_cpu": 2, "cores_per_socket": 1, "memory_mb": 4096, "hardware_version": "vmx-21", "guest_id": "otherGuest64",
 "cpu_reservation_mhz": 0, "cpu_limit_mhz": -1, "cpu_shares": "normal",
 "memory_reservation_mb": 0, "memory_limit_mb": -1, "memory_shares": "normal",
 "devices": {"disk:2000": {"label": "Hard disk 1", "uuid": "6000C29a-0000-0000-0000-000000000001", "capacity_kb": 10485760, "thin": true, "disk_mode": "persistent"},
             "nic:4000": {"label": "Network adapter 1", "adapter": "VirtualVmxnet3", "network": "VM Network",
                          "start_connected": true, "mac_address": "00:50:56:00:00:01"}}}
```

差分は、正規化した値を比べて作る。要素の集まりの場所は、`host_vswitch`・`host_portgroup` では値の全体（最上位の辞書のキーが要素）、`vm_config` では `devices` の下だけである。`host_build`・`cluster_ha`・`cluster_drs` と、`vm_config` の `devices` 以外の項目には要素が無い。配列の項目（`uplinks`・`active_nics`・`failover_hosts` など）は、要素の集まりではなく、丸ごと 1 つの値として比べる。要素の中の項目は、項目ごとに比べる。

`element` は、要素の集まり（vSwitch・ポートグループの名前、`disk:<key>`・`nic:<key>`）のキーで、要素の無い項目では NULL になる。差分の行の例:

| 変化 | `element` | `attribute` | `old_value` | `new_value` |
|---|---|---|---|---|
| CPU の数を 2 から 4 に | NULL | `num_cpu` | `2` | `4` |
| vSwitch0 の MTU を 1500 から 9000 に | `vSwitch0` | `mtu` | `1500` | `9000` |
| ディスクを足した | `disk:2001` | NULL | NULL | `{"label":"Hard disk 2","capacity_kb":…}` |
| 同じ key のディスクが別の `uuid` に入れ替わった | `disk:2000` | NULL | `{"label":"Hard disk 1","uuid":"6000C29a-…",…}` | NULL |
| （同じ観測の 2 行め） | `disk:2000` | NULL | NULL | `{"label":"Hard disk 1","uuid":"6000C29b-…",…}` |
| NIC のポートグループを替えた | `nic:4000` | `network` | `"VM Network"` | `"App Network"` |
| HA の監視を設定から外した | NULL | `host_monitoring` | `"enabled"` | `null` |

- 要素が増えたら、`attribute` を NULL、`old_value` を NULL にし、`new_value` に要素の項目全体の JSON を入れる。減ったら逆にする。
- 値が None（設定していない）なら、`old_value`・`new_value` には文字列の `null` が入る。行の NULL（要素が無い）と区別するためである。
- `old_value`・`new_value` は、値を JSON にした文字列である。1,024 文字を超えたら切り詰め、`truncated` を真にする。

`value_hash` は、正規化した値を `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` で文字列にし、UTF-8 の SHA-256 を 16 進で取ったものにする。

正規化の規則を後の版で変えると、すべての行で差分が出てしまう。そこで、種類ごとに正規化の版（`format`、最初は 1）を持つ。保存した行の版が今の版と違えば、差分を記録せずに値だけを入れ替える（3 章）。VM は、版が違えば段 2 で読み直す（上の「読み方」）。

## 3. 保存の形

### 表

- **`inventory_config_states`**（構成の今の値）
  - `id`、`vcenter_id`（FK → vcenters、`ondelete="CASCADE"`）、`moid`（256）、`category`（32）
  - `entity_type`（256）、`entity_name`（1024）。観測のたびに、変わっていれば今の値に更新する。
  - `format`（Integer。正規化の版）
  - `value`（JSON。正規化した値）、`value_hash`（64）
  - `change_version`（256、NULL 可。`vm_config` だけ）
  - `verified_at`（今の値が有効だったと最後に確かめた時刻。3 章の「時刻の意味」）
  - 一意: `(vcenter_id, moid, category)`
- **`inventory_config_diffs`**（差分）
  - `id`、`vcenter_id`（FK → vcenters、`ondelete="CASCADE"`）、`moid`（256）、`category`（32）
  - `entity_type`（256）、`entity_name`（1024）。差分を記録した時点の値を写す。差分は 30 日残るが、`inventory_objects` は 7 日で消えるので、結合に頼らない。
  - `element`（1024、NULL 可）、`element_label`（1024、NULL 可。ディスクと NIC の、記録したときのラベル。要素が減ったときは古い値の、それ以外は新しい値のラベルを写す。vSwitch とポートグループは要素の名前、要素の無い項目は NULL）、`attribute`（64、NULL 可）
  - `old_value`・`new_value`（Text、NULL 可）、`truncated`（Boolean）
  - `changed_after`（前の値を最後に確かめた時刻）、`observed_at`（新しい値を読んだ観測の時刻）
  - CHECK: `changed_after <= observed_at`
  - 索引: `(vcenter_id, moid, observed_at)`、`(observed_at)`（保持期間の削除）
- **`inventory_sync_states` に列を足す:** `config_instance_uuid`、`config_first_success_at`、`config_last_started_at`、`config_last_success_at`、`config_last_failure_at`、`config_last_error`（Text）、`config_last_warning`（Text）、`config_last_warning_at`、`config_object_count`、`config_deferred_count`。

### 時刻の意味

構成が変わった本当の時刻は、`changed_after` と `observed_at` の間のどこかである（`changed_after` を含まず、`observed_at` を含む）。差分には、この 2 つの時刻を両方とも残す。画面と報告書は「○○ から △△ の間に変わった」と出す。

- **`verified_at`:** その行の値が有効だったと確かめた観測の、構成の読み取りを始めた時刻（段 1 の要求を出す直前の本体の時刻）である。値は読み取りの途中で読むので、読み始めの時刻なら「この時刻には前の値だった」と言える。本体の時計が戻っても小さくならないよう、`max(今回の読み始め, 前の verified_at)` で更新する。持ち越した行と、段 2 で読み残した VM の行は、`verified_at` を動かさない。
- **`changed_after`:** 前の値の行の `verified_at` である。持ち越しや読み残しが続いた行は、最後に確かめた時刻まで幅が広がる。ESXi の更新で再起動を挟むと、切断の間は持ち越すので、幅は切断の前の観測から始まる。
- **`observed_at`:** 構成の読み取りを終えた時刻（スレッドの中で段 2 を終えた時刻）である。本体の時計が戻ったときに区間が逆転しないよう、`max(読み終わりの時刻, changed_after)` にする。
- 関係の観測の時刻 `t` は、構成の読み取りを待たず、関係を読み終えた時刻にする（今は読み取りの後に `utcnow()` で取っているので、関係の結果に読み終わりの時刻を持たせる）。構成の読み取りの分だけ、関係の `valid_from` が遅れないようにするためである。

### スレッドと時間

- スレッドは、関係の結果と構成の結果を、別々の `Future` で返す。関係の `Future` は関係を読み終えた時点で値が入り、構成の `Future` は構成の読み取りを終えた時点で値か例外が入る。
- 非同期の側は、関係の `Future` を受け取ったら、すぐに関係を保存する。その後で、構成の `Future` を、残りの時間（`inventory_sync_timeout_seconds` から経過した時間を引いた分）だけ待つ。間に合わなければ、構成の読み取りのタイムアウトとして記録する（関係の記録は残る）。今の `_reads` によるスレッドの数の管理は、スレッドが終わるまで続ける。そのため `_reads` の枠は、スレッドが生きている間（`thread.is_alive()`）は空けない。構成の `Future` は切断の前に値が入るので、枠の判定には使わない（関係や構成の `Future` で判定すると、切断の途中で枠が空き、同じ vCenter の読み取りが重なったり、スレッドが 3 つ以上になったりする）。構成の読み取りが無効なときや、関係の読み取りで例外が出たときも、スレッドの `finally` で、構成の `Future` にかならず値（読まなかったことを表す値）か例外を入れる。
- スレッドの中の締め切りは、スレッドの開始から `inventory_sync_timeout_seconds` の 8 割とする。段 1 の各ページの前と、段 2 の各組の前で締め切りを見る。
  - 段 1 で締め切りを過ぎたら、構成の読み取りの失敗にする（段 1 は全件を読み終えないと使えない）。
  - 段 2 で締め切りを過ぎたら、新しい組を読み始めず、残りの VM を「読み残し」として返す。
  - 1 回の要求そのものは途中で止められず、最大で `http_connection_timeout` かかる。その場合は、非同期の側のタイムアウトになる。
- スレッドが返す型は、PR B で `collectors/` に決める。構成の結果には、管理対象ごとの正規化した値（種類ごと）、持ち越す種類、段 2 で読めなかった VM、読み残した VM、`change_version`、読み始めと読み終わりの時刻、使ったクラスタのパス（新旧）を入れる。
- モックのモードでは、関係と構成の両方をモックの定義から作る。段 2 の対象の選び方（`change_version` の比較）は本物と同じ関数を通し、読み残しは出さない。

### 更新の手順（vCenter ごと）

1. **読み取りの前（DB）:** その vCenter の `vm_config` の行から、`moid` ごとの `change_version` と `format` を読み、スレッドに渡す。構成の読み取りが無効なら、構成の読み取りをしないようにスレッドに伝える。
2. **読み取り（スレッド）:** 関係を読んだ後に、2 章の段 1 と段 2 を読む（上の「スレッドと時間」）。
3. **関係の保存:** 今までどおり `persist_inventory` で保存する。関係の読み取り（タイムアウトを含む）か保存が失敗したら、構成は保存せず、構成の読み取りが有効なら構成の失敗にも同じ文言を記録する（状態の画面で、構成が止まっている理由が分かるようにする）。
4. **構成の保存（別のトランザクション）:**
   1. **記録のやり直し:** `config_instance_uuid` が NULL でなく、観測の `instance_uuid` と違えば、その vCenter の `inventory_config_states` をすべて消し、`config_first_success_at` を今回の `config_last_success_at` と同じ値にする。差分は記録せず、今回の値を初めての値として入れる。関係の `reset` とは別に、構成の側で比べる。関係の `reset` が起きた回に構成の読み取りが失敗しても、次の構成の成功でやり直せるようにするためである。
   2. 段 1 で見えた管理対象ごとに、種類ごとに次のどれかを行う。
      - **持ち越し（値と `verified_at` を変えない）:** 次のどれかに当たるとき。
        - 接続していないホスト（`runtime.connectionState` が `connected` でない）のすべての種類。
        - 接続していない VM（同じく `connected` でない。孤立・アクセスできない VM）の `vm_config`。
        - 元の属性が `missingSet` に入った種類。
        - 元の属性が `propSet` に無い種類（途中が未設定のパスは、`missingSet` にも入らずに消える）。
        - 元の属性の値そのものが None の種類（`dasConfig` が None など）。
        - 段 2 で読めなかった VM（`ManagedObjectNotFound` で外した、必ず要る属性が欠けた、どれかの属性が `missingSet` に入った、ディスクの元の backing が分からない）の `vm_config`。
      - 空の配列（vSwitch が 1 つも無い）は持ち越しではなく、空の値として比べる。`propSet` に無いことと、空の配列で返ることを区別するためである。区別が実機でどう出るかは、7 章の道具で確かめる。
      - **読み残し（何もしない）:** 段 2 で読み残した VM の `vm_config`。`change_version` も古いままにするので、次の観測で読み直す。
      - **初めての値:** 保存した行が無い。差分は記録せず、行を入れる（`verified_at` は今回の読み始め）。
      - **正規化の版が違う:** 差分は記録せず、値と版を入れ替える。
      - **変わった:** `value_hash` が違う。2 章の規則で差分の行を入れ、値を入れ替える。
      - **同じ:** 値は変えない。
      - 判定は上から順に行う。持ち越しに当たるかを、下の近道より先に見る。
      - VM で、持ち越しに当たらず、段 1 の `config.changeVersion` が保存した値と同じで、版も同じなら、段 2 で読まずに「同じ」とする。
   3. 持ち越しと読み残しを除いたすべての行（初めて・版の違い・変わった・同じ）の `verified_at` を、`max(今回の読み始め, 前の verified_at)` にする。行の数が多いので、`id` を並べた一括の UPDATE（executemany）で行う。`entity_name`・`entity_type` が変わった行も、ここで更新する。
   4. 保存した行のうち、段 1 で見えなかった管理対象（削除、テンプレートへの変更、権限で見えない）の行を消す。再び見えたら、初めての値として入れ直す（見えなかった間の差分は記録しない）。
   5. `config_instance_uuid`、`config_last_started_at`（今回の読み始め）、`config_last_success_at`（`max(今回の読み終わり, 前の config_last_success_at)`）、`config_object_count`、`config_deferred_count`（読み残した VM の数）を更新する。初めての成功なら `config_first_success_at` を、`config_last_success_at` と同じ値にする。
5. **構成の失敗:** 段 1・段 2 の例外、構成のタイムアウト、構成の保存の失敗は、`_record_failure` と同じく別のトランザクションで `config_last_failure_at` と `config_last_error` に残す。`config_last_error` は `_safe_error` と同じ基準で整える。構成の行と差分は変えない。

### 警告

1 回の観測で、種類（`category`）ごとに、比べた行（「変わった」と「同じ」の行。近道で「同じ」とした VM を含み、持ち越し・読み残し・初めて・版の違いは数えない）が 20 以上あり、そのうち半分以上が「変わった」種類があれば、記録はしたうえで `config_last_warning` と `config_last_warning_at` に残す。vCenter の更新で値の表し方が変わった、権限の変更で値が読めるようになった、などで大量の差分が出たことに、管理者が気づけるようにするためである。要素の名前の重なり（2 章）も、同じ列に警告として残す。

### 設定と保持期間

- `inventory_config_enabled`（既定は真）: 偽なら構成の読み取りをしない。関係の収集（`inventory_sync_enabled`）が偽なら、これが真でも読まない。
- `inventory_config_retention_days`（既定 30、下限 1）: 差分の保持期間。
- 保持期間の削除（`purge_old_inventory`）に足す: `observed_at` が `now - inventory_config_retention_days` より前の差分。
- `inventory_config_states` は時刻では消さない（今の値なので）。管理対象が見えなくなったときと、vCenter を削除したとき（CASCADE）に消える。
- 構成の読み取りを無効にしている間も、今の値の行は残る。再び有効にした最初の観測では、`verified_at` が古いので、差分の幅が無効にしていた期間だけ広がる。

### モック

- `mocks/mock_inventory.py` に、構成の観測を足す。今のモックの管理対象（クラスタ 1・ホスト 2・VM 3）に合わせる。関係と同じく、モックとシードが同じ定義を使うようにする。シードとモックがずれると、最初の観測で差分が出てしまう。
- 通常のモックでは、関係と同じ 30 分の枠で、VM 1 台の CPU の数が 2 と 4 で入れ替わるようにする。`config.changeVersion` は、正規化した値の `value_hash` から作る。
- スクリーンショット用の vCenter（`SCREENSHOT_VCENTER_NAME`）では、値を固定する（PR C のシードの最後の値と同じにする）。

### 量の見積もり

- **読み取り:** 段 1 は、ホストのポートグループの `port`（ポートごとに数十バイト）が大半である。ホスト 100 台・ホストあたり VM 50 台（計 5,000 台）で、毎回 1 MB 前後の見込みである（登録済みの vCenter はホスト 1 台・VM 21 台で、段 1 の全体が約 13 KB・0.17 秒だった）。段 2 は、最初の観測だけ全 VM（5,000 台で 60 MB 前後）を読み、その後は変わった VM だけを読む。最初の観測で締め切りを過ぎたら、残りは次の観測に回る。
- **保存:** 今の値は、管理対象と種類ごとに 1 行で、VM 5,000 台なら 5,500 行前後、1 行は数百バイトから 2 KB 程度である。`verified_at` の一括の UPDATE は、観測のたびにこの行数だけ動く。差分は、変わった項目ごとに 1 行で、30 日で数万行の見込みである。
- 実機の値は、7 章の道具で確かめる（登録済みの vCenter は VM 21 台と小さいので、大きな環境は見積もりのままになる）。

## 4. API（PR C）

### 差分の一覧

`GET /api/inventory/config-diffs?vcenter_id=…&entity_moid=…&from=…&to=…`（viewer 以上）。

- `vcenter_id` と `entity_moid` は必須にする。`entity_moid` は影響範囲の API と同じく `min_length=1`・`max_length=256` にする。
- `from` と `to` は `UtcDateTime` で受ける。両方を省いたら、`from` は現在時刻から保持期間を引いた時刻、`to` は現在時刻と最後の構成収集の成功時刻の遅い方にする。片方だけのときと、`from > to` のときは 422 にする。vCenter が無ければ 404 にする。
- 返すのは、変化の幅が期間と重なる差分である（`changed_after < to` かつ `observed_at > from`）。
- 並びは `observed_at` の降順、`id` の降順で、最大 200 件と総数を返す。
- 応答:
  - `target`（moid・種別・名前。名前と種別は、見えなくなった対象も含めて `inventory_objects` の行から取り、行が無ければ最新の差分の値を使う）
  - `status`: `disabled`（構成の読み取りが無効）、`not_recorded`（一度も構成の読み取りに成功していない）、`ok` のどれか。`disabled` でも、残っている差分は返す。
  - `recorded_since`（`max(config_first_success_at, now - inventory_config_retention_days)`）、`last_success_at`（`config_last_success_at`）
  - `items`: `id`・`category`・`category_label`・`element`・`element_label`・`attribute`・`attribute_label`・`old_value`・`new_value`（JSON として読み直した値。`truncated` が真なら文字列のまま）・`truncated`・`changed_after`・`observed_at`
  - `total`
- 差分は観測した項目の違いである。API の説明（OpenAPI の description）と画面・報告書の文言では、同じ装置が続いていた、または差分が無いので交換も無かった、と言い切らない（2 章の「装置の入れ替わり」）。同じ `element` に同じ観測で「減った」行と「増えた」行があれば、画面と報告書は「入れ替わり」としてまとめて出してよい。
- 種類と項目の表示名は、バックエンドの定義から返す。画面と報告書で同じ名前を使うためである。例: `host_vswitch` は「標準 vSwitch」、`num_cpu` は「CPU の数」、ディスクの `uuid` は「ディスクの UUID」。2 章の表のすべての項目に表示名を付ける。`element_label` は差分の行の列をそのまま返す（ラベルが無ければ `element` のまま）。今の値の行は、管理対象が見えなくなると消え、ラベルが変われば書き換わるので、後から引かない。
- 差分は LLM に渡さない（チャットとダイジェストには入れない）。

### カードへの差分の添付

`IncidentTimelineConfigChange` に次を足す。

- `diffs: list[IncidentTimelineConfigDiff] | None = None`
- `diffs_total: int = 0`

`IncidentTimelineConfigDiff` は、一覧の `items` と同じ項目を持つ。

添付の規則:
- `_ConfigChangeGroup` に、組の行が持つ `(vcenter_id, entity_moid)` の集まりを足し、`add()` で集める。これをカードの対象とする。chain でまとめたカードは、クラスタとホストのように対象を複数持つことがある。
- `diffs` を None にするのは、次のどれかのとき。構成の読み取りが無効でも、残っている差分は添える（一覧の API と同じく、欄とカードで見える差分をそろえる）。
  - カードの `vcenter_id` が None のとき。
  - カードの vCenter で、一度も構成の読み取りに成功していない（`config_first_success_at` が NULL）とき。
  - カードの `last_utc` が `recorded_since` より前のとき（記録の無い時期のカード）。
  - カードの対象に moid が 1 つも無いとき。
  - 足す前に保存した結果（既定値で None になる）。
- それ以外は、判定して 0 件でも空の配列にする。
- 差分の対象がカードの対象に含まれ、変化の幅がカードの時刻と重なる差分を添える。重なりは `changed_after < last_utc + 2 分` かつ `observed_at > first_utc - 2 分` で判定する。2 分は、vCenter の時計（イベントの時刻）と本体の時計（観測の時刻）のずれを見込んだ幅である。`first_utc`・`last_utc` は、カードの値（まとめた行の最初と最後の時刻）をそのまま使う。
- カードごとに、件数（COUNT）と、`observed_at` の昇順・`category`・`element`・対象（`vcenter_id`・`moid`）・`attribute`・「減った」行を先（`new_value IS NULL` を先）・`id` の順の最初の 10 件を読み、`diffs` と `diffs_total` に入れる。文字列はバイト順で、`element` の NULL は先に、`attribute` の NULL は後に置く。入れ替わりの 2 行（同じ観測・同じ対象・同じ `category`・同じ `element` の「減った」行と「増えた」行）は、10 件の切れ目で分けない。10 件目が入れ替わりの「減った」行なら、対の「増えた」行も入れる（その場合だけ 11 件になる）。一覧の API の 200 件の切れ目も同じにする。カードは最大 20 枚なので、SELECT は最大 40 回である。
- 同じ差分が、複数のカードに添わることがある（同じ VM の再構成が、1 回の観測の間に 2 回あった場合など）。どちらにも添える。

カードに添わらない差分（イベントの無い変更、ESXi を直接操作した変更）は、タイムラインの対象の欄でだけ見える。

### 出力（案 10）

- 報告書（`report.md`）の「### 構成変更」の節で、カードごとに差分を字下げして書く（例: 「CPU の数: 2 → 4（12:30 から 12:40 の間）」）。`diffs_total` が実際に表示した件数を超えれば、残りの件数を書く。無害化の規則は、ほかの節と同じにする。
- `items.csv` は変えない（一覧の行には項目を足さない）。
- `result.json` には、足した項目がそのまま入る。

### 収集の状態

`GET /api/inventory/status` の vCenter ごとの項目に、`config_*` の列（`config_instance_uuid` を除く）を足す。設定の `config_enabled` は、構成の読み取りが実際に動くかどうか（`scheduler_enabled`・`inventory_sync_enabled`・`inventory_config_enabled` のすべてが真）を返す。

### シード

スクリーンショット用のシード（`dev/screenshot_e2e_seed.py`）に、次を足す。テスト（`tests/test_screenshot_e2e_seed.py`）も合わせる。

- 今の値の行（3 章のモックのスクリーンショット用の値と同じ）と、`config_instance_uuid`（モックと同じ固定値）・`config_first_success_at`（差分とホストのメンテナンスより前）・`config_last_success_at`。
- `demo-vm-01` の差分: CPU の数 2 → 4、メモリ 4,096 → 8,192 MB。幅はシードの `VmReconfiguredEvent`（45 分前）と、そのタスク（44 分前）を含むようにする（55 分前から 40 分前）。カードに添わる例になる。
- 差分の行には `element_label` も入れる。
- `demo-esxi-01` の差分: ポートグループの VLAN の変更。対応するイベントは入れない。対象の欄でだけ見える例になる。

## 5. 画面（PR D）

### タイムラインの「構成の差分」の欄

- タイムラインで対象を moid で絞ったときだけ、影響範囲の欄（`TimelineImpactSection`）の隣に出す。
- 期間は、タイムラインの期間（`from`・`to`）を使う。タイムラインの応答を待たずに要求してよい（影響範囲と違い、既定の時点を応答から決める必要が無い）。期間と対象が同じなら、読み込み直しても、別のタブから戻っても、要求し直さない。
- 差分を新しい順に並べ、1 行に「種類・要素・項目: 古い値 → 新しい値」と、変化の幅（「12:30 から 12:40 の間」）を出す。要素が増えた・減ったときは「追加」「削除」と出し、項目を折りたたみで出す。
- 200 件を超えたら「N 件のうち新しい 200 件を出しています」と出す。
- `status` ごとの表示:
  - `disabled`: 「構成の差分の記録は無効です」。残っている差分があれば、その下に出す。
  - `not_recorded`: 「まだ構成を読み取っていません」と、設定の vCenter の一覧への案内
  - `ok` で 0 件: 「この期間に観測した構成の差分はありません」。期間の始まりが `recorded_since` より前なら、「記録は ○○ から」と添える。
- 変化の時刻は観測の時刻で決まり、幅があることを、短い注記で出す。
- 差分の無いことを「変更なし」と言い切らない。注記は「観測した項目に違いはありません」のように、観測した範囲であることが分かる書き方にする。同じ観測で同じ要素の「削除」と「追加」があれば「入れ替わり」と出す。

### カード

- 構成変更のカード（`TimelineHighlights.tsx`）の各項目の下に、添えた差分を出す。`diffs` が None か空なら、何も出さない。
- `diffs_total` が出した件数より多ければ、「ほか N 件」と出し、対象で絞ったときの欄で全件を見られることを添える。
- 画面の zod のスキーマでは、`diffs` と `diffs_total` を省略可（nullish と既定値）にする。足す前に保存したスナップショットの結果を読めるようにするためである。

### 設定の収集の状態

設定の vCenter の一覧の、関係の収集の状態（案 1 の PR D）の隣に、構成の読み取りの状態（最後の成功、最後の失敗とその内容、警告、読み残した VM の数）を出す。最後の失敗が最後の成功より新しいときは「失敗中」として目立たせる。

- 画面の zod のスキーマ（`frontend/src/api/schemas/` とそのテスト）と、API の呼び出しの関数を足す。
- 文書: `docs/userguide/timeline.md`（構成の差分の欄とカードの差分、「外部に渡すときの確認」）、`docs/features/config-change-detection.md`（イベントによる検出と、差分の記録の関係）、設定の文書、`docs/operations/backend-operations.md`（設定の 2 つ）、CHANGELOG。
- スクリーンショット: 対象の欄とカードの差分を、明暗の両方のテーマで撮る（PR C のシードを使う）。

## 6. PR の分け方

### PR A: 本書

本書だけを入れる。

### PR B: 構成の読み取り、保存、差分の記録

- `collectors/` に、構成の読み取り（段 1・段 2・パスの代わり・`ManagedObjectNotFound` の読み直し）と正規化の関数を足す。正規化は pyVmomi の型に頼らず、属性を `getattr` で読む純粋な関数にし、テストでは偽オブジェクトで値を与える。
- `services/inventory.py` の流れを、3 章の「スレッドと時間」と「更新の手順」に変える。
- 移行（`inventory_config_states`、`inventory_config_diffs`、`inventory_sync_states` の列）と、移行のテスト（`tests/test_db_session_migrations.py` の書き方に合わせる）。
- 設定の 2 つと、保持期間の削除。
- モック（3 章）。
- テスト。少なくとも次を確かめる。どのテストも、その守りを外すと落ちることを確かめる。
  - 比べる項目に無い値（`port`・`numPortsAvailable`・`numPorts`・`fileName`・`connected`）だけが変わっても、差分が出ない。`auto_compute` が真のときの割合の変化でも出ない。
  - アップリンクの並びだけが変わっても差分が出ず、アクティブ・スタンバイの順が変わると差分が出る。
  - 装置のラベルだけが変わると `label` の差分が出て、装置の並び順が変わっても差分が出ない（キーが `key` であること）。
  - 同じ `key` のディスクで `uuid` が違うと、項目の差分ではなく「減った」行と「増えた」行が出る。`uuid` が片方 None なら項目ごとに比べる。同じ `key`・同じ `uuid` で項目が違えば項目の差分が出て、すべて同じなら差分が出ない。同じ `key` の NIC の交換は、項目が違えば項目の差分、すべて同じなら差分なしになる（Issue #397 の合成テスト）。
  - 初めての値、正規化の版の違い、`config_instance_uuid` の違い（関係の `reset` の回に構成が失敗した後の回を含む）で、差分が出ない。
  - 接続していないホストと VM、`missingSet`、`propSet` に無い属性、値が None のときに持ち越し、`verified_at` を動かさない。再び読めた回の `changed_after` が、持ち越しの前の `verified_at` になる。
  - `changeVersion` と版が同じ VM を段 2 で読まない。版が違う VM は読む。読み残しの順。読み残した VM の `change_version` と `verified_at` が動かず、次の観測で読まれる。
  - `ManagedObjectNotFound` で VM を外して読み直す。
  - `InvalidProperty` でクラスタのパスを替えて読み直す。
  - 構成の読み取りの例外とタイムアウトで、関係の記録が残り、構成の失敗が記録される。関係の保存の失敗で、構成の失敗も記録される。
  - 関係の `t` が、構成の読み取りを待たずに決まる。
  - 見えなくなった管理対象の行が消え、再び見えたら差分なしで入る。
  - 要素の増減と、値の None と行の NULL の区別。切り詰めと `truncated`。
  - 大量の差分の警告と、その分母。
  - 保持期間の削除。
- CI の PostgreSQL の手順（`ci.yml:221-230`）に、新しいテストのファイルと `-k` のキーワード（`config_diff`）を足す（1 章）。
- 実機の確認の道具（7 章）を `scripts/` に足し、テストを付ける。
- マージの前に、利用者が実機で道具を実行し、結果を本書の 2 章に書く。結果によって比べる項目や持ち越しの規則を変えるときは、PR B の中で直す。

### PR C: API

- 4 章のとおり。差分の一覧の API、カードへの添付、報告書、収集の状態、シード。
- CHANGELOG（API の追加）。

### PR D: 画面と文書

- 5 章のとおり。

各 PR は origin/main から作ったブランチで進める。実装は Codex に任せ、critic がレビューする。画面の依頼では、`docs/development/frontend.md` の「実装とレビューで確かめること」を指す。

## 7. 確認方法

### 実機の確認の道具（PR B）

`scripts/probe_inventory_config.py` を足す。登録済みの vCenter の名前を引数に取り、本体の DB から接続情報を読み、構成の読み取りだけを行う（DB にも vCenter にも書き込まない）。利用者が実行して出力を貼る。

- 段 1 のパスごとに、成功したか、失敗した例外の型（`InvalidProperty` など）を出す。`configurationEx.dasConfig` が失敗したら、`configuration.dasConfig` も試して結果を出す。
- パスごとに、`propSet` にあった件数、`missingSet` に入った件数、どちらにも無かった件数、空の配列だった件数を出す。
- 種類ごとの管理対象の数、直列化した大きさ（バイト）、段 1 と段 2 の時間を出す。段 2 は、全 VM を読んだときの値を出す。`ManagedObjectNotFound` が出たかも出す。
- ディスクの件数を出す: 差分ディスク（`parent` のある）の数（`disks_with_parent`）、今の backing と元の backing で `thin` が違う数（`disks_with_different_thin`）、元の backing に `uuid` がある数とない数（`disks_with_uuid`・`disks_without_root_uuid`）、差分ディスクの `uuid` が元のディスクと違う数（`disks_with_different_uuid`）。
- 間を空けて 2 回読み（既定 300 秒、引数で変えられる）、次を出す。
  - 正規化した値が変わった種類と項目の名前と、その件数（構成を変えていないのに変わる項目を見つけるため）。
  - `config.changeVersion` が変わった VM の数（バックアップの製品のスナップショットなどで、どれだけ変わるかを見るため）。
- 管理対象の名前・moid・値・ホスト名と、要素のキー（vSwitch・ポートグループの名前、装置の key）は出さない。出すのは、パス、種類、項目の名前、件数、大きさ、時間、例外の型だけにする。

確かめること:
- 段 1・段 2 のパスが実機で使えるか（特に `configurationEx.dasConfig`。登録済みの vCenter では使えず、古いパスを先に使うことにした）
- `propSet` に無い属性と空の配列の出方
- 構成を変えずに 2 回読んで、差分が出ないか
- 読み取りの量と時間
- ディスクの `uuid` が元の backing で読めるか、差分ディスクの `uuid` が元のディスクと違うか（違うなら、今の backing から読むと入れ替わりを誤って記録することになり、元の backing から読む規則の根拠になる）

### 自動のテスト

- PR B: 6 章のテスト。全体の pytest、`scripts/ci_postgres_local.py`（CI の PostgreSQL の手順）、mypy、ruff。
- PR C: API とカードの添付と報告書のテスト。保存済みのスナップショットの結果（`diffs` の無い JSON）が読めること。
- PR D: vitest、tsc、ESLint と、スクリーンショット。

## 8. 範囲外（後続）

- マルチパスのポリシー、分散スイッチとその上のポートグループ、vSAN の設定。
- `configurationEx` のルール、VM ごとの上書き、グループ。
- ホストの詳細の設定（`config.option`）、サービス、ファイアウォール、NTP。
- イベントの無い差分を、タイムラインのハイライトに出すこと（今は対象の欄でだけ見える）。
- VM の差分を、そのホストやクラスタの対象の欄にも出すこと（影響範囲の関係をたどる）。
- 差分を LLM に渡すこと。渡すなら、値に入る名前（ポートグループ名など）の匿名化を先に決める。
- 外部のプラグインから構成を入れること（プラグイン API の種類の追加）。

## 9. リスク

- **変化の時刻の幅:** 差分の時刻は観測の時刻で、本当の変化は前の値を最後に確かめた時刻との間のどこかである。幅はふつう、観測の間隔と読み取りの時間の和で、失敗・切断・読み残しが続くと広がる。画面と報告書は幅のまま出す。カードへの添付は幅との重なりで判定するので、同じ幅に入った別の変更の差分も添わることがある。
- **実機と vcsim の違い:** 実機の確認は、ホスト 1 台・VM 21 台の小さな vCenter 1 台だけである（2 章の「確かめた結果（実機）」）。この環境では、`missingSet` に入った属性、`propSet` に無い属性、空の配列が 1 件も無く、その扱いは実機では確かめていない。構成を変えなくても変わる項目も、300 秒の間隔の 2 回の読み取りでは見つからなかったが、DRS の移動やスナップショットの作成をまたぐ間隔では確かめていない。
- **最後の vSwitch を消したとき:** vSwitch が 1 つも無くなったホストで、属性が空の配列でなく `propSet` に無い形で返るなら、持ち越しになり、削除は記録されない。
- **大量の差分:** vCenter や ESXi の更新で値の表し方が変わると、多くの行で差分が出る。警告で知らせる（3 章）。本体の正規化を変えるときは、`format` を上げて差分を出さない。
- **読み取りの量:** 最初の観測では全 VM の装置を読む。大きな環境では締め切りで読み残し、次の観測に回る。その間の VM の差分は、幅が広がる。
- **バックアップの製品のスナップショット:** 毎晩スナップショットを取る環境では、多くの VM の `config.changeVersion` が変わり、段 2 で多くの VM を読み直すことになる。読み残しと幅の広がりが毎晩起きるおそれがある。7 章の道具で、`changeVersion` が変わる VM の数を確かめる。
- **持ち越しと見えない値:** 接続していないホストと VM の値は、切断の前の値のまま残る。権限で一部の値が見えないときも、前の値のまま残る。見えなくなった管理対象の行は消すので、再び見えたときの変化は記録しない。
- **元のディスクを付け替える操作:** リンククローンのディスクの昇格、vCD の高速プロビジョニングの統合、Horizon の再構成のように、ディスクを替えずに元の backing そのものが別のファイルに替わる操作では、`uuid` が変わり、「入れ替わり」（削除と追加）として記録されうる。7 章の道具では、差分ディスクと元のディスクの `uuid` の違いまでしか確かめられない。
- **装置の key の使い回し:** 装置の `key` は、外した後に別の装置に使い回されることがある。ディスクは `uuid` の違いで入れ替わりを見分けるが、`uuid` を持たない古い形式のディスクと NIC は見分けられない。その場合、交換は項目の差分として見えるか、項目がすべて同じなら見えない（Issue #397）。
- **値に入る情報:** ポートグループ名・ネットワークの識別子・MAC アドレスが値に入る。viewer も見られる（イベントの一覧の対象の名前と同じ扱い）。報告書と `result.json` にも入るので、ユーザーガイドの「外部に渡すときの確認」に書く。保存したスナップショットの結果（既定 90 日）にも残る。
- **記録のやり直しの前の差分:** `config_instance_uuid` が変わって記録をやり直しても、古い vCenter の差分は同じ `vcenter_id` のまま保持期間まで残る。moid が重なると、やり直しより前の期間を指定したときに、新しい対象の差分のように見える。イベントや案 1 の関係の閉じた行も同じ扱いである。一覧の API は `recorded_since`（やり直しの時刻以降）を返すので、画面はそれより前の差分に「記録をやり直す前の値」と注記する。
- **moid が変わる操作:** VM の登録し直しや、Linked Mode の vCenter をまたぐ移動では moid が変わり、別の管理対象として初めての値になる。
- **記録の始まりと保持期間:** 機能を入れる前と、保持期間より前の差分は無い。`recorded_since` で示す。
