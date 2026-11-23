# 影響範囲マップ（インベントリの関係を集める）

最終更新: 2026-11-23（計画）

[障害調査を楽にする機能 10 案](2026-11-22-troubleshooting-ideas.md)（以下「10 案」）の「案 1」にあたる。前提の「案 0b」（Issue #347）は済んでいる。「案 5」（[既知の障害パターン](2026-11-23-event-patterns.md)）は、本書の関係を使うと、クラスタやデータストアでまとめられるようになる（後続）。

本書の用語は、[イベントの対象の計画書](2026-11-23-event-entities.md) に合わせる。vCenter の管理対象を一意に指す ID（`host-10` のような値）を **moid** と呼ぶ。VM・ホスト・クラスタ・データストア・ネットワークの親子や利用の関係を **関係** と呼ぶ。1 回の収集で vCenter の関係を読んで保存することを **観測** と呼ぶ。コードの場所は、バックエンドを `src/vcenter_event_assistant/` から、画面を `frontend/src/` から書く。行番号は、本書を書いた時点の origin/main（0dfa8e3）のものである。

## 進捗

| PR | 内容 | 状態 |
|---|---|---|
| A | 本書 | レビュー中 |
| B | 関係の収集と保存（表、移行、定期ジョブ、保持期間の削除、モック） | 未着手 |
| C | 影響範囲と収集の状態の API | 未着手 |
| D | 画面（タイムラインの「影響範囲」の欄、設定の収集の状態） | 未着手 |

各 PR は単独でマージでき、テストが通る状態にする。

## Context

障害の調査では、「このホスト（データストア、ポートグループ）が落ちたら、どの VM に及ぶか」をまず知りたい。今は、イベントとメトリクスを対象ごとに見られるだけで、対象どうしの関係（VM がどのホストに載り、どのデータストアとネットワークを使っているか）を持っていない。moid から名前を引く処理（`services/alerting/alert_entity_resolution.py`）も、メトリクスやイベントの記録を使うだけである。

さらに、HA や vMotion で VM が移ると、今の関係だけでは「障害の時点で、そのホストにどの VM が載っていたか」が分からない。そこで、関係の変化の履歴を集めて保存し、タイムラインで対象を選んだときに、その時点の影響範囲を出す。

決めたこと（利用者の決定）:
- 関係は、変化の履歴として残す（いつからいつまで、の形）。保持期間はイベントと同じにする。
- 最初の版で集めるのは、ホスト・VM・クラスタ・データストア・ネットワーク（標準と分散のポートグループ）の関係である。分散スイッチやリソースプールは後続にする。
- 影響範囲は、まずタイムラインの対象の欄に出す。API も用意する。図（グラフの絵）は後続にする。
- 収集は本体の定期ジョブで行い、プラグイン API は変えない。

## 1. 前提（コードで確かめたこと）

- **プラグイン API:** データの種類はイベント・メトリクス・ログの 3 つだけである（`DataKind`、`PLUGIN_API_VERSION = 1`）。組み込みのコレクタも、この API の上で本体の中で動く（`plugins/builtin.py`）。関係を入れる種類は無いので、本体のジョブで集める（利用者の決定）。外部のプラグインから関係を入れることはできない。
- **vCenter への接続:** `collectors/connection.py` の `connect_vcenter`・`disconnect`・`read_connection_info`（`instance_uuid` を返す）がある。プラグイン API の `vmware.container_view` は ContainerView を開いて `list(view.view)` を返し、`finally` で `Destroy()` する。View そのものは返さないので、PropertyCollector には使えない（2 章）。
- **今の収集:** 管理対象の属性を pyVmomi で 1 つずつ読む（`collectors/perf.py`、`collectors/datastore_metrics.py`）。属性を読むたびに vCenter に問い合わせるので、数千台の VM の関係をこの方法で読むと遅い。
- **プラグインの実行:** `plugins/runtime.py` は、vCenter からの収集を DB のセッションの外で行い、`(plugin_id, vcenter_id)` ごとの `asyncio.Lock`（`_locks`）と、全体の同時実行の上限（`_limiter`、`ingestion_concurrency`）で守る。失敗は別のトランザクションで記録し（`_mark_failed`）、例外の文字列は `_safe_error` で整える。
- **スケジューラ:** `jobs/scheduler.py` に、コレクタの登録（288-298 行。`poll_events`・`poll_perf` は旧来のジョブ ID で、実体は `run_registered_collector`）、アラートの評価、配送、保持期間の削除（`purge_retention`、113-144 行）などのジョブがある（299-323 行）。間隔は設定（`settings.py`）で持ち、`_job_options_for_interval` で misfire の猶予を付けて登録する。`collector:` で始まるジョブは、プラグインの再読み込み（`reconcile_collector_jobs`）が付け外しする。ジョブのテストは `tests/test_scheduler_job_options.py`。
- **保持期間:** `event_retention_days`（`settings.py:71`、既定 7 日）。削除は `purge_retention` から種類ごとの関数（`purge_old_events`、`services/ingestion.py:259` など）を呼ぶ。vCenter を削除すると、関係のある表は DB の `ON DELETE CASCADE` で消える（SQLite では `PRAGMA foreign_keys=ON`、`db/session.py:25` が前提。新しい表にも `ondelete="CASCADE"` を付ける）。
- **モック:** `settings.mock_mode`（`settings.py:342`）で、組み込みのコレクタは `fetch_mock`・`sample_mock` を使う。モックの対象は `mocks/mock_collectors.py` にあり、今はホスト・VM・データストアが 1 つずつで、クラスタとネットワークは無い。シードは `dev/mock_mode_seed.py` と `dev/screenshot_e2e_seed.py`（`SCHEDULER_ENABLED=false` で動く）にある。
- **日時:** API の日時は `UtcDateTime`（`api/schemas/base.py:23`）で UTC にそろえる。SQLite は日時を文字列で比べるので、UTC にそろえないと比較がずれる。
- **移行:** head は `f9a0b1c2d3e4`（PR #361）。実装のときに origin/main で確かめ直す。
- **タイムライン:** 対象を moid で絞ると、要求に `vcenter_id` と `entity_moid` が入る（PR #358・PR #359）。画面の条件は URL のハッシュに載る。
- **pyVmomi で確かめたこと:** 属性のパス（VM の `runtime.host`・`runtime.connectionState`・`datastore`・`network`・`config.template`・`summary.config.template`、ホストの `parent`・`datastore`・`network`・`runtime.connectionState`）と、`RetrievePropertiesEx`・`ContinueRetrievePropertiesEx`・`CancelRetrievePropertiesEx`・`RetrieveOptions.maxObjects`・`ObjectContent.missingSet`・`TraversalSpec(type=ContainerView, path="view")` は存在する。`DistributedVirtualPortgroup` と `OpaqueNetwork` は `vim.Network` の部分クラスである。

## 2. 集める関係

### 読み方

コアの `collectors/` に、関係を読む専用の関数を作る（プラグイン API には足さない）。

- rootFolder から、再帰の ContainerView を 1 つ自前で開く（型は下の表の 5 つ）。
- `ObjectSpec(obj=view, skip=True, selectSet=[TraversalSpec(type=ContainerView, path="view", skip=False)])` と、型ごとの `PropertySpec` で `RetrievePropertiesEx` を呼び、`token` が None になるまで `ContinueRetrievePropertiesEx` で続ける。`RetrieveOptions.maxObjects` は 1,000 にする（目安で、少なく返ることがある）。
- 途中で例外が出たら、`token` があれば `CancelRetrievePropertiesEx(token)` を呼ぶ。View は `finally` で `Destroy()` する。
- 管理対象の参照からは `_moId` と `_wsdlName` だけを読み、`name` などを `getattr` で読まない（読むと vCenter に問い合わせる。対象の計画書と同じ制約）。名前は、取得した属性（`propSet`）から取る。

| 型 | 読む属性 |
|---|---|
| `VirtualMachine` | `name`・`runtime.host`・`runtime.connectionState`・`datastore`・`network`・`summary.config.template` |
| `HostSystem` | `name`・`parent`・`datastore`・`network`・`runtime.connectionState` |
| `ClusterComputeResource` | `name` |
| `Datastore` | `name` |
| `Network`（`DistributedVirtualPortgroup`・`OpaqueNetwork` を含む） | `name` |

- 次の事項は、PR B の初めに、利用者の許可を得て登録済みの vCenter で読み取り専用で確かめ、結果を本書に書き足す。
  - `Network` の指定で部分型（`DistributedVirtualPortgroup`・`OpaqueNetwork`）が取れるか
  - アカウントから見えない管理対象がどう返るか（参照だけが返るか、何も返らないか）
  - 接続していないホストと、接続していない・アクセスできない VM の `datastore`・`network` が空で返るか
  - vCenter をファイルベースで復元したとき、`instance_uuid` が変わるか（確かめられなければ、変わらない前提で 9 章の制約にする）

### 関係の種類

| 種類 | 子 → 親 | 元の属性 |
|---|---|---|
| `vm_host` | VM → ホスト | `VirtualMachine.runtime.host` |
| `host_cluster` | ホスト → クラスタ | `HostSystem.parent`（`ClusterComputeResource` のときだけ） |
| `vm_datastore` | VM → データストア | `VirtualMachine.datastore[]` |
| `host_datastore` | ホスト → データストア | `HostSystem.datastore[]` |
| `vm_network` | VM → ネットワーク | `VirtualMachine.network[]` |
| `host_network` | ホスト → ネットワーク | `HostSystem.network[]` |

- VM からクラスタは、その時点の `vm_host` と `host_cluster` をたどって求める（保存しない）。
- `host_network` には、分散スイッチのアップリンクのポートグループも入る。最初の版では区別しない。

### 欠けた値と例外の扱い

- **テンプレート:** `summary.config.template` が真の VM は、管理対象にも関係にも入れない（収集では見えないものとして扱う）。VM をテンプレートに変えると、その VM は `removed_at` が付き、関係は閉じる。テンプレートを VM に戻すと、再び現れる。値が欠けたら、テンプレートでないとみなす。
- **属性の欠け（`missingSet`）:** 権限の不足（`NoPermission`）などで、ある管理対象の属性が欠けたら、その属性から作る関係の種類は、その管理対象について前回の開いている関係を持ち越す（閉じない）。誤って閉じて、復旧後に開き直す履歴を作らないためである。
- **接続していないホストと VM:** `runtime.connectionState` が `connected` でないホストは `host_datastore`・`host_network` を、同じく接続していない VM は `vm_datastore`・`vm_network` を、前回から持ち越す。障害の最中に、関係がいったん全部閉じ、復旧後に開き直すのを避けるためである（`host_cluster` と `vm_host` は、読めた値で更新する）。
- **持ち越しの条件:** 持ち越すのは、今回の観測で子と親の両方が見えている関係だけにする。相手が消えた関係（切断中のホストから削除されたデータストアなど）まで持ち越すと、永久に閉じないためである。
- **名前:** vCenter は `ManagedEntity.name` の `/`・`\`・`%` を `%2f`・`%5c`・`%25` に置き換えて返す。既存の収集と同じく、置き換わったまま保存する（イベントやメトリクスの名前と合わせるため）。
- **件数の急な減り:** 管理対象の数が前回の成功から半分以下に減ったら、更新は行うが、状態に警告（`last_warning`・`last_warning_at`）を残す。権限の変更などで大量の関係が閉じたことに、管理者が気づけるようにするためである。警告は、次の警告で上書きするまで残し、画面には時刻を添えて出す。

## 3. 保存の形

### 表

- **`inventory_objects`**（管理対象の今の名前と種別）
  - `id`、`vcenter_id`（FK → vcenters、`ondelete="CASCADE"`）、`moid`（256）、`entity_type`（256、`HostSystem` の形）、`name`（1024）
  - `first_seen_at`、`removed_at`（NULL 可。観測で見えなくなった時刻）
  - 一意: `(vcenter_id, moid)`
  - 名前の履歴は持たない（障害の時点の名前は、イベントの子表 `event_entities` に残る）。「最後に見えた時刻」は持たず、`removed_at` が NULL なら、最後の観測で見えたとみなす（毎回の全件の更新を避けるため）。
- **`inventory_relations`**（関係の履歴）
  - `id`、`vcenter_id`（FK → vcenters、`ondelete="CASCADE"`）、`kind`（32）、`child_moid`（256）、`parent_moid`（256）
  - `valid_from`（観測した時刻）、`valid_to`（NULL 可。観測されなくなった時刻）
  - CHECK: `valid_to IS NULL OR valid_to >= valid_from`
  - 索引: `(vcenter_id, parent_moid, kind, valid_from)`、`(vcenter_id, child_moid, kind, valid_from)`
  - 部分一意索引: `valid_to IS NULL` の行で `(vcenter_id, kind, child_moid, parent_moid)`。モデルと移行の両方に、`sqlite_where` と `postgresql_where` の両方を書く（片方だけだと、もう片方の DB で WHERE の無い一意索引ができ、閉じた後に同じ組を開き直せなくなる）。
  - `valid_to` には索引を付けない。保持期間の削除は 1 日数回で、行数も小さいので、走査を許容する。
- **`inventory_sync_runs`**（成功した観測の時刻）
  - `id`、`vcenter_id`（FK → vcenters、`ondelete="CASCADE"`）、`observed_at`
  - 索引: `(vcenter_id, observed_at)`
  - 観測していない期間（収集が止まっていた、失敗が続いた）を見分けるために使う（4 章）。既定の間隔なら 1 日 144 行、7 日で約 1,000 行である。
- **`inventory_sync_states`**（vCenter ごとの収集の状態）
  - `vcenter_id`（主キー、FK → vcenters、`ondelete="CASCADE"`）
  - `instance_uuid`（観測した vCenter の `instance_uuid`）
  - `first_success_at`（関係の記録が始まった時刻）、`last_started_at`、`last_success_at`、`last_failure_at`、`last_error`（Text）、`last_warning`（Text）、`last_warning_at`
  - `object_count`、`relation_count`（直近の成功の件数）

### 更新の手順（vCenter ごと）

1. **読み取り（DB のセッションの外）:** 2 章のとおりに読み、関係の集合 `S`、管理対象の一覧、`instance_uuid` を作る。観測の時刻 `t` は、読み終わった時点（書き込みの直前）の本体の時刻（UTC）にする。読み始めの時刻にすると、読み取りの途中で起きた変化（障害の直後の HA の再起動など）が、本当の変化より前の時刻で記録されるためである。
2. **書き込み（1 つのトランザクション）:**
   1. `t = max(t, last_success_at)` にそろえる（本体の時計が戻っても、区間が逆転しないように）。
   2. `instance_uuid` が前回と違えば、別の vCenter（接続先の変更など）とみなす。開いている関係をすべて `t` で閉じ、管理対象すべてに `removed_at = t` を入れ、`first_success_at = t` にして記録をやり直す。前回の値が NULL（初回）なら比べない。空文字どうしは同じとみなす（`read_connection_info` は値が無いと空文字を返す）。
   3. 開いている関係（`valid_to IS NULL`）の集合 `O` を読む。2 章の持ち越しの分（`O` のうち、持ち越しの条件に合うもの）を `S` に足す。
   4. `S - O` を `valid_from = t` で入れ、`O - S` の行に `valid_to = t` を入れる。どちらもまとめて実行する（executemany）。
   5. 管理対象は、名前・種別・`removed_at` が変わったものだけを更新し、新しいものを入れる。前回まで見えていて今回見えないものに `removed_at = t` を入れ、再び見えたら NULL に戻す。
   6. `inventory_sync_runs` に `t` を入れ、`inventory_sync_states` を更新する。初めての成功なら `first_success_at = t` にする。
- 読み取りや書き込みに失敗したら、関係と管理対象は変えない。失敗は、別のトランザクションで `inventory_sync_states` に記録する。`last_error` は `plugins/runtime.py` の `_safe_error` と同じ基準で整える（サーバの応答や接続先の情報を残さない）。
- 収集の途中で vCenter が削除されたら（書き込みで FK の違反）、失敗として扱い、記録もしない。
- 関係が変わった本当の時刻は、前回と今回の観測の間のどこかである。`valid_from` と `valid_to` は観測した時刻であり、記録は本当の変化と同時か、それより遅れる。遅れは、最大で観測の間隔と読み取りの時間の和である（9 章）。

### 同時実行とタイムアウト

- 既存の取り込みの仕組みは使わない。`services/ingest_runner.py` の `_ingest_run_slot` はプロセス全体の busy の目印で、使うと関係の収集の間、イベントの取り込みが飛ばされる。`plugins/runtime.py` の `_limiter` を共有すると、遅い関係の収集が取り込みの枠を占める。
- 同じプロセスの中では、ジョブの `max_instances=1` と、vCenter ごとの `asyncio.Lock` で守る。複数のプロセスで動いたときは、部分一意索引の違反を失敗として記録する（次の観測でそろう）。
- vCenter ごとに `asyncio.timeout`（設定 `inventory_sync_timeout_seconds`、既定 300）を付ける。1 台の vCenter が遅くても、次の vCenter に進む。
- 読み取りは、関係の収集の専用の `ThreadPoolExecutor`（スレッドは少数）で動かす。既定の executor は、取り込みの接続（`plugins/runtime.py` の `connect_vcenter`）と共有なので、応答の無い vCenter でタイムアウトしたスレッドが溜まると、取り込みまで止まるためである。タイムアウトしても、スレッドの中の pyVmomi の呼び出しは止まらない。前回のスレッドが終わっていない vCenter は飛ばし、失敗として記録する。

### 定期ジョブと設定

- 設定: `inventory_sync_enabled`（既定は真）、`inventory_sync_interval_seconds`（既定 600、下限 60）、`inventory_sync_timeout_seconds`（既定 300）。
- ジョブ ID は `inventory_sync` にする（`collector:` で始めず、`reconcile_collector_jobs` の対象にしない）。`scheduler_enabled` が真で、`inventory_sync_enabled` が真のときだけ登録する。
- 有効な vCenter ごとに、順に収集する。接続とブロッキングの処理は、上の専用のスレッドに退避する。無効にした vCenter と、`inventory_sync_enabled` を偽にしたときは収集しない。そのとき、閉じた関係と観測の記録は保持期間で消えるが、開いている関係と見えている管理対象は、vCenter を削除するまで残る。API は、最後の観測から時間が経つので `stale` を返す。
- モックのモードでは vCenter に接続せず、モックの関係で同じ更新の手順を通す（3 章の「モック」）。
- 保持期間の削除（`purge_retention`）に足す:
  - `valid_to` が `now - event_retention_days` より前の関係
  - `removed_at` が同じく前の管理対象
  - `observed_at` が同じく前の観測の記録

### モック

- `mocks/` に、モックの関係を足す。クラスタ 1 つ、ホスト 2 台、VM 数台、データストア 2 つ、ポートグループ 2 つにする。今のモックのホスト・VM・データストアの moid と名前に合わせる。
- 時刻（例: 30 分の枠）で、VM 1 台がホストの間を移るようにする。モックのモードで、関係が閉じて開く様子を確かめるためである。
- モックの `instance_uuid` は固定値にする。
- シード（`dev/mock_mode_seed.py`・`dev/screenshot_e2e_seed.py`）は、モックの出力と同じ開いている関係、HA で VM が移った履歴（閉じた行）を 1 件、`inventory_sync_runs` と `inventory_sync_states`（`first_success_at` は履歴の行より前、`instance_uuid` はモックと同じ固定値）を入れる。シードとモックがずれると、最初のジョブで関係が閉じられたり、記録のやり直しが起きたりするので、同じ定義から作る。

### 量の見積もり

VM 5,000 台、1 台あたりデータストア 2・ネットワーク 2 なら、開いている関係は約 2.5 万行になる。閉じた行は、vMotion・HA・構成の変更のたびに増える。DRS が頻繁に動く環境や vCLS の VM の移動が多い環境では、7 日で数万行になり得る。収集のたびに開いている関係を全部読むが、この量なら 1 回の SELECT で足りる。

## 4. API（PR C）

### 影響範囲

`GET /api/inventory/impact?vcenter_id=…&entity_moid=…&at=…&from=…&to=…`（viewer 以上）。

- `at`・`from`・`to` は `UtcDateTime` で受ける。`at` を省いたら今の時刻にし、`max(今の時刻, last_success_at)` より後なら、その値に丸める（本体の時計が戻って `t` が張り付いた間の行も見えるように）。`from` と `to`（省略可）は、期間中の変化を返すときに使う。
- 時刻 `at` の関係は、`valid_from <= at` かつ（`valid_to IS NULL` または `valid_to > at`）の行である。
- 対象の種別は、`inventory_objects.entity_type` で決める。無ければ、`event_entities` の同じ `(vcenter_id, moid)` の最新の種別で補う。どちらにも無ければ、`unknown_target` にする。
- 「ネットワーク」は、種別が `Network`・`DistributedVirtualPortgroup`・`OpaqueNetwork` のものとする。
- `status` は、次の順で最初に当たるものにする。

| 順 | status | 条件 |
|---|---|---|
| 1 | （404） | `vcenter_id` の vCenter が無い |
| 2 | `unsupported_type` | 種別が、集める 5 つ（ホスト・VM・クラスタ・データストア・ネットワーク）のどれでもない（Datacenter・ResourcePool・DVS・Folder など） |
| 3 | `not_recorded` | `at` が `recorded_since` より前。`recorded_since = max(first_success_at, now - event_retention_days)`。`inventory_sync_states` の行が無い（一度も成功していない）ときも、これにする |
| 4 | `unknown_target` | 対象が `inventory_objects` に無い（アカウントから見えない、まだ観測していない） |
| 5 | `absent_at_time` | `first_seen_at > at`、または `removed_at <= at`（その時点の観測で、対象が見えていない） |
| 6 | `stale` | `at` 以前の最後の成功した観測 `prev` が無い（保持期間の削除で消えた直後など）、または `at - prev > 2 × inventory_sync_interval_seconds` |
| 7 | `ok` | 上のどれでもない |

- `stale` のときも一覧は返す。画面は、観測の時刻（`prev` と、`at` の後の最初の観測 `next`）を添えて注意を促す。`absent_at_time` でも、観測の時刻を添える（観測が止まっていた間に作られた対象は、その間の時点でも「見えていない」になるため）。
- 対象の種別によって、次のものを返す。

| 対象 | 返すもの |
|---|---|
| ホスト | クラスタ、載っている VM、データストア、ネットワーク |
| VM | ホスト、クラスタ（その時点のホストを経由）、データストア、ネットワーク |
| クラスタ | ホスト、その時点でそれらのホストに載っている VM |
| データストア | 使っているホスト、使っている VM |
| ネットワーク | 使っているホスト、使っている VM |

- 応答:
  - `target`（moid・種別・名前）、`at`、`status`
  - `recorded_since`、`last_success_at`、`observed_before`（`prev`）、`observed_after`（`next`）
  - `groups`: 種類ごとの一覧（`relation`・`items`・`total`）。`items` は moid・種別・名前・`removed`（今は見えない対象か）。名前、moid の順に並べ、1 つの種類につき 200 件までにして、`total` に総数を入れる。
  - `changes`（`from` と `to` を渡したときだけ）: 期間中に開いた関係と閉じた関係（種類・相手・時刻・開いたか閉じたか）。最大 200 件と総数。`from` は `recorded_since` で切り詰める（記録のやり直しで一斉に閉じて開いた行を、変化として出さないため）。
- 名前は `inventory_objects` の今の名前を使う。名前が無ければ moid を出す。
- 影響範囲の情報は LLM に渡さない（チャットとダイジェストには入れない）。

### 収集の状態

`GET /api/inventory/status`（viewer 以上）で、vCenter ごとの `inventory_sync_states`（`last_error` を含む）と、設定の間隔を返す。画面の設定（PR D）で使う。

## 5. 画面（PR D）

### タイムラインの「影響範囲」の欄

- タイムラインで対象を moid で絞ったとき（URL に `entity_moid` があるとき）だけ出す。名前の文字列だけで絞っているときは出さない（対象が 1 つに決まらないため）。
- 時点の既定は、次の順で決める。障害の後に HA や vMotion で VM が移っても、障害の時点の状態を見られるようにするためである。
  1. 起点があれば起点
  2. 無ければ、ハイライトの「最初の兆候」（`highlights.first_signal`）の時刻（moid で絞っているので、その対象の最初の注目すべき出来事）
  3. それも無ければ、期間の始まり
- 影響範囲の要求は、タイムラインの応答を待ってから出す。選んだ種別（sources）と `min_score` によって「最初の兆候」が変わるので、既定の時点もそれに従って変わる。タイムラインが 422（件数が多すぎる）で応答を返さないときは、期間の始まりを使う。
- 欄の中で、時点を「期間の始まり」「期間の終わり」に切り替えられる。
- 種類ごとに件数と名前の一覧を出し、長い一覧は折りたたむ。項目の「この対象で絞る」で、その対象の moid で絞る（PR #359 と同じ操作）。
- 期間中の変化（`changes`）を、折りたたみで出す（例: 「vm-12 が esx-02 から esx-03 へ」）。
- `status` ごとの表示:
  - `not_recorded`: 「この時点の関係は記録されていません（記録は ○○ から）」。保存したスナップショット（保持 90 日）を開いたときは、関係（保持 7 日）が消えていることが多いので、この表示になる。
  - `unknown_target`: 「この対象の関係の記録がありません」（まだ観測していない対象と、保持期間の削除で記録が消えた対象の両方を含む）
  - `unsupported_type`: 「この種類の対象の影響範囲は出せません」
  - `absent_at_time`: 「この時点の観測では、この対象は見えていませんでした」と観測の時刻
  - `stale`: 一覧に添えて「この時点の前後は ○○ と △△ に観測しています。その間の変化は反映していません」
- 最後の収集の時刻を出す。観測の時刻は最大で収集の間隔だけずれることを、短い注記で出す（9 章）。

### 設定の収集の状態

設定の vCenter の一覧に、関係の収集の状態（最後の成功、最後の失敗とその内容、警告、件数）を出す。権限の不足などで失敗が続いても、管理者が気づけるようにするためである。

- 画面の zod のスキーマ（`frontend/src/api/schemas/` とそのテスト）と、API の呼び出しの関数を足す。
- 文書: `docs/userguide/timeline.md`、設定の文書、CHANGELOG。

## 6. PR の分け方

### PR A: 本書

- 本書を足す。
- [既知の障害パターンの計画書](2026-11-23-event-patterns.md) の進捗の表を直す（PR D をマージ済みにする）。

### PR B: 関係の収集と保存

- 初めに、2 章の「確かめる事項」を、利用者の許可を得て登録済みの vCenter で読み取り専用で確かめ、本書に書き足す。
- 4 つの表と移行。移行のテストを、既存の書き方に倣って足す。部分一意索引は、閉じた後に開き直せることを、SQLite と PostgreSQL の両方で確かめる。
- 収集（PropertyCollector）、更新の手順、同時実行とタイムアウト、定期ジョブ、設定、保持期間の削除、モック、シード。
- テスト:
  - 更新の手順:
    - 新しい関係が開くこと、無くなった関係が閉じること、変わらない関係はそのままであること
    - 持ち越し（属性の欠け、接続していないホスト）
    - テンプレートの切り替え
    - 管理対象の `removed_at` の付け外しと、変わったものだけの更新
    - 時計が戻ったとき
    - `instance_uuid` が変わったときのやり直し
    - 件数が急に減ったときの警告
    - 失敗のときに何も変えないこと、失敗の記録が別のトランザクションであること
    - `first_success_at` は初回だけ付くこと
  - 収集: pyVmomi の型で作った PropertyCollector の応答から、関係と管理対象が正しく作られること。応答は次の場合を作る。
    - ページが続く場合
    - テンプレート
    - 単体のホスト
    - 空の配列
    - `missingSet`
    - 接続していないホスト

    あわせて、例外のときに `CancelRetrievePropertiesEx` と `Destroy` が呼ばれること、名前の属性を `getattr` で読まないことを確かめる。
  - 同時実行: 同じ vCenter の収集が重ならないこと。タイムアウトのあと次の vCenter に進むこと。
  - スケジューラ: `tests/test_scheduler_job_options.py` の `_INTERVAL_JOB_IDS`・`_INTERVAL_JOB_MISFIRE` に `inventory_sync` を足す。設定が偽なら登録しないこと。
  - 保持期間の削除、vCenter の削除での CASCADE。
  - モックとシード: `tests/test_mock_mode.py`、`tests/test_screenshot_e2e_seed.py` を直す。
  - SQLite と PostgreSQL の両方での挿入と更新（`tests/services/test_aggregation_dialects.py` に倣う）。
- CI（`.github/workflows/ci.yml` の `auth-postgres`）:
  - `-k` は、その step に並べたファイルの中からしか選ばない。PostgreSQL で流すテストを新しいファイルに置くときは、step にそのファイルのパスも足す。
  - 移行の step の `-k "postgres and (event_entity or event_entities)"` に `inventory` を足す。
  - 方言の step の `-k "postgres and (entity_moid or event_pattern)"` に `inventory` を足す。
  - テスト名には `inventory` を含める。部分一意索引で閉じた後に開き直せることが、PostgreSQL の step で流れることを確かめる。
- 文書:
  - `docs/development/backend.md`（表と更新の手順）
  - `docs/operations/backend-operations.md`（420 行付近の設定の一覧、176 行付近の保持期間の点検、必要な権限、タイムアウトの注意）
  - `docs/features/features_list.md`（145 行付近の表の一覧）
  - `.env.example`（91-101 行付近）
  - `docs/userguide/mock-mode.md`
  - CHANGELOG

### PR C: API

- 4 章のとおり。
- テスト:
  - 種別ごとの返すもの
  - 時刻 `at` の境界（`valid_from` ちょうどは含み、`valid_to` ちょうどは含まない）
  - HA で VM が移った後でも、前の時刻ではもとのホストに出ること
  - ホストのクラスタの移動を、その時点でたどること
  - `status` のすべてと優先順位
  - オフセット付きの `at` と、未来の `at`
  - 並び、200 件の上限と総数、`changes`
  - 権限（viewer で 200、匿名で 401）と route policy
  - SQLite と PostgreSQL の両方
- CI: PR C の PostgreSQL のテスト（名前に `inventory` を含める）が、方言の step で選ばれること（新しいファイルに置くなら、step にパスを足す）。
- 文書: `docs/development/backend.md`、CHANGELOG。

### PR D: 画面

5 章のとおり。vitest のテストを足し、画面のスクリーンショットを PR に添える。

## 7. 確認方法

- PR B: モックのモードで起動し、ジョブが関係を入れること。モックの VM がホストを移ると、前の行が閉じて新しい行が開くこと。保持期間を過ぎた行が消えること。
- PR C: シードの関係で、ホスト・VM・クラスタ・データストア・ネットワークのそれぞれを引けること。HA で移った VM が、障害の前の時刻ではもとのホストに出ること。観測の間が空いた時点で `stale` になること。
- PR D: タイムラインで対象を moid で絞ると「影響範囲」が出て、時点を切り替えられること。項目から別の対象で絞れること。設定の vCenter の一覧に収集の状態が出ること。

## 8. 範囲外（後続）

- 影響範囲の図（グラフの絵）
- 分散スイッチ、リソースプール、vApp、フォルダの関係
- 外部のプラグインから関係を入れること（プラグイン API の種類の追加）
- 変化の本当の時刻を、vMotion・HA のイベントから補うこと
- vCLS の VM を除くこと（見分け方を確かめてから）
- 「案 5」の障害パターンを、クラスタやデータストアの関係でまとめること（例: HA の障害ホストに載っていた VM で結ぶ、データストアの障害を 1 件にまとめる）。障害パターンの検知から影響範囲を開くこと。
- 「案 2b」（構成の差分）の記録
- 影響範囲をチャットやダイジェストに渡すこと。渡すときは moid を含むので、LLM への匿名化（PR #356）を通す。

## 9. リスク

- **観測の時刻のずれ:** 関係の `valid_from` と `valid_to` は観測した時刻（読み終わりの時刻）で、本当の変化と同時か、それより遅れる。遅れは最大で観測の間隔（既定 10 分）と読み取りの時間の和である。障害の直前に vMotion した VM は、前のホストに載っていたように見えることがある。画面に注記を出す。
- **観測していない期間:** 収集が止まっていた間、失敗が続いた間は、その前の関係が続いていたものとして記録される（次の観測で閉じる）。`stale` と観測の時刻で示す。
- **時計のずれ:** 観測の時刻は本体の時計、イベントの時刻は vCenter の時計である。両者がずれると、起点の時点の関係がずれて見える。本体の時計が戻ったときは、`t = max(t, last_success_at)` で区間の逆転を防ぐ。その間に開いた関係は、`valid_from` が今の時刻より後になる（API の `at` の丸めで見えるようにする）。
- **見えなかった区間は残らない:** 管理対象の `removed_at` は、再び見えると NULL に戻す。テンプレートに変えて戻した VM や、権限で一時的に見えなかった対象は、見えなかった間の時点でも `absent_at_time` にならず、関係の無い `ok` になる。存在の区間の履歴は持たない（最初の版の制約）。
- **見えない管理対象:** 収集のアカウントから見えない管理対象は、関係に入らないか、参照だけが返る見込みである（PR B で確かめる）。影響範囲は「見えた範囲」である。文書に書く。権限が変わって一部が見えなくなると、大量の関係が閉じる。件数の急な減りは警告に残す。
- **vCenter の付け替え:** 登録した vCenter の接続先を変えると、同じ moid が別のものを指し得る。`instance_uuid` の変化で記録をやり直す。vCenter をファイルベースで復元したときは `instance_uuid` も戻る見込みで、その場合は検知できない（PR B で確かめる）。
- **moid が変わる操作:** Linked Mode の vCenter をまたぐ vMotion や、VM の登録し直しでは moid（と vCenter）が変わり、履歴が切れる。
- **大きな環境:** VM が数万台なら、1 回の収集の応答と、開いている関係の読み込みが大きくなる。ページで読み、更新はまとめて実行し、変わった管理対象だけを更新する。重ければ間隔を延ばす（設定）。タイムアウトしたスレッドは残る。
- **記録の始まりと保持期間:** 機能を入れる前の時点や、保持期間より前の時点の関係は無い。`not_recorded` で示す。保存したスナップショットは 90 日残るが、関係は 7 日で消える。
