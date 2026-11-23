# イベントの対象（名前・種別・moid）を正しく保存する

最終更新: 2026-11-23（計画）

Issue #347 の計画書。[障害調査を楽にする機能 10 案](2026-11-22-troubleshooting-ideas.md) の #0b にあたる。

本書では、vCenter の管理対象（ホスト、VM、データストアなど）を一意に指す ID（`host-10` のような値）を **moid** と呼ぶ。イベントが指す管理対象を **対象** と呼ぶ。

## 進捗

| PR | 内容 | 状態 |
|---|---|---|
| A | 本書 | マージ済み [PR #352](https://github.com/t-m0riyama/vcenter-event-assistant/pull/352) |
| B | 対象の取り出しと、主な対象の名前・種別（DB の変更なし。plugin-api 1.6.0） | マージ済み [PR #353](https://github.com/t-m0riyama/vcenter-event-assistant/pull/353) |
| C1 | moid と子表の保存（移行、plugin-api 1.7.0、取り込みの経路） | マージ済み [PR #354](https://github.com/t-m0riyama/vcenter-event-assistant/pull/354) |
| C2 | API と画面（`EventRead.entity_moid`、フロントの zod と CSV） | レビュー中 |

各 PR は単独でマージでき、テストが通る状態にする。

## Context

`normalize_event`（`src/vcenter_event_assistant/collectors/events.py`）は `e.entity` しか見ていない。そのため、ほとんどのイベントで `entity_name` と `entity_type` が空になる。

- `HostConnectionLostEvent` では、どのホストの接続が切れたかが残らない。
- `entity` を持つアラームのイベントでは、`entity_type` に引数の型（`vim.event.ManagedEntityEventArgument`）が入る。
- moid は、どのイベントでも保存していない。

イベント一覧の対象の表示、タイムラインの対象での絞り込み、「影響の大きい対象」に、ホスト系のイベントが結び付かない。障害調査の計画の影響範囲マップ（#1）、構成の差分（#2b）、既知の障害パターン（#5）は、イベントと対象を moid で結び付けることが前提になる。

決めたこと:

- 主な対象（1 件に 1 つ）は events 表の列に持つ。主でない対象（VM のイベントのホスト、vMotion の移動元、HA の障害ホストなど）も、子表にすべて保存する。
- 種別は `HostSystem` の形で書く（`vim.` を付けない）。
- 対象を取り出す処理は plugin-api に 1 か所だけ置き、本体・雛形・例のコレクタから使う。
- 保存済みの行は直さない。保持期間が過ぎれば入れ替わる。

## 1. 前提（コードと pyVmomi で確かめたこと）

pyVmomi は 9.0.0.0 で確かめた。

### 対象はイベントのいろいろな属性にある

- 基底型 `vim.event.Event` は、`datacenter`・`computeResource`・`host`・`vm`・`ds`・`net`・`dvs` の 7 属性を持つ。どれも `*EventArgument` で、`name` と管理対象の参照（例: `HostEventArgument.host`）を持つ。基底型に `entity` は無い。
- 基底型に無い属性として、管理対象の参照を持つ引数か管理対象そのものを持つ型が、**105 種類** ある。主な属性と型の数は次のとおり。

| 属性 | 型の数 | 例 |
|---|---|---|
| `entity` | 28 | アラーム 13、スケジュールタスク 9、権限 4、`CustomFieldValueChangedEvent`、`GeneralUserEvent` |
| `datastore` | 19 | `DatastoreRemovedOnHostEvent`、`DatastoreDestroyedEvent` |
| `destHost` / `destDatastore` / `destDatacenter` | 9 / 5 / 5 | `VmBeingMigratedEvent`、`VmBeingClonedEvent` |
| `resourcePool` | 6 | `ResourcePoolCreatedEvent` |
| `sourceHost` / `sourceDatastore` / `sourceDatacenter` | 4 / 5 / 3 | `VmMigratedEvent`、`DrsVmMigratedEvent` |
| `parent` / `oldParent` / `newParent` | 4 / 2 / 2 | `ClusterCreatedEvent`（親フォルダ）、`ResourcePoolMovedEvent` |
| `isolatedHost` / `failedHost` | 3 / 1 | `DasHostIsolatedEvent`、`DasHostFailedEvent` |
| `hostJoined` / `hostLeft` / `hostBackInSync` / `hostMember` | 1 ずつ | `DvsHostJoinedEvent` など |
| `conflictedVm` / `conflictedVms[]` / `conflictedHosts[]` | 4 / 2 / 2 | `VmMacConflictEvent`、`HostWwnConflictEvent`（`[]` は配列） |
| `dstHost` / `dstPool` | 4 / 2 | `MigrationHostErrorEvent` |

- 明示された対象を持つ型がある。
  - `entity`（`ManagedEntityEventArgument` が参照を `.entity` に包む）。アラームの `source` は、アラームの定義元である。
  - EventEx の `objectId`・`objectType`・`objectName`。`objectType` は、SOAP から戻すと型（`vim.HostSystem` のクラス）になる。プラグインや偽オブジェクトは、文字列で渡すことがある。
  - ExtendedEvent の `managedObject`（名前を持たない）
- 宣言された型と実際の値が違うものがある。
  - `VmDeployFailedEvent.destDatastore` は `EntityEventArgument` で、参照を持たない（名前だけ）。上の表の `destDatastore` の 5 には数えていない。
  - `ProfileReferenceHostChangedEvent.referenceHost` は、引数ではなく管理対象そのものである。名前は別の属性 `referenceHostName` にある。
- 入れ子の中に対象を持つ型がある。
  - `DvsHostWentOutOfSyncEvent.hostOutOfSync.outOfSyncHost`、`OutOfSyncDvsHost.hostOutOfSync[].outOfSyncHost`（`DvsOutOfSyncHostArgument` は `EventArgument` の子ではない）
  - `DvsPortConnectedEvent` / `DvsPortDisconnectedEvent` の `connectee.connectedEntity`
  - `TaskEvent` / `TaskTimeoutEvent` の `info.entity`（名前は `info.entityName`）と `info.locked[]`
  - そのほか、`HostEnableAdminFailedEvent.permissions[].entity`、`HostSpecificationUpdateEvent.hostSpec.host`、`DvsReconfiguredEvent` などの `configSpec.*`
- `reason`（23 型）や `fault`（8 型）のように、中に参照を持つ値がある（例: `ManagedObjectNotFound.obj`）。これらは対象ではない。
- `vim.event.EventArgument` の子クラスは次のとおりである。
  - インベントリの参照を持つもの: `ComputeResourceEventArgument`・`DatacenterEventArgument`・`DatastoreEventArgument`・`DvsEventArgument`・`FolderEventArgument`・`HostEventArgument`・`ManagedEntityEventArgument`・`NetworkEventArgument`・`ResourcePoolEventArgument`・`VmEventArgument`
  - 名前だけのもの: `EntityEventArgument`（上の 10 種類と、アラーム・スケジュールタスクの引数の親）
  - インベントリでない参照を持つもの、または参照を持たないもの: `AlarmEventArgument`・`ScheduledTaskEventArgument`・`ProfileEventArgument`・`RoleEventArgument`
- 管理対象の型名は `vim.HostSystem`、`_wsdlName` は `HostSystem`。`ManagedEntity` の子クラスは、次の 16 種類である。
  - `ClusterComputeResource`・`ComputeResource`・`Datacenter`・`Datastore`
  - `DistributedVirtualPortgroup`・`DistributedVirtualSwitch`・`Folder`・`HostSystem`
  - `ManagedEntity`・`Network`・`OpaqueNetwork`・`ResourcePool`
  - `StoragePod`・`VirtualApp`・`VirtualMachine`・`VmwareDistributedVirtualSwitch`
- SOAP から戻した管理対象には、vCenter への接続（スタブ）が付く。その `name` を読むと、vCenter に問い合わせる（`InvokeAccessor`）。失敗したときの例外は `AttributeError` ではないので、`getattr(obj, "name", None)` では止まらない。

### 今の値と使われ方

- 組み込みのコレクタが実際の vCenter から取った行の `entity_type` は、`None` か `vim.event.ManagedEntityEventArgument` のどちらかである。
- 一方で、メトリクス（`collectors/perf.py`・`datastore_metrics.py`）、モック（`mocks/mock_collectors.py`）、シード（`dev/mock_mode_seed.py`・`dev/screenshot_e2e_seed.py`）、テスト、画面のフィクスチャは、どれも `HostSystem`・`VirtualMachine`・`Datastore` の形を使う。例のコレクタは `type(entity).__name__` を入れている（`examples/example-event-collector/src/example_event_collector/__init__.py:161`）。
- イベントとメトリクスは、名前の文字列でしか結び付いていない。
  - タイムラインの絞り込みは、`entity_name` の部分一致（`services/incident_timeline_view.py:846`）。
  - 「影響の大きい対象」は、`(vcenter_id, entity_name)` の完全一致（同 `:612`）。
  - ログの対象の種別は `host`（同 `:122`）。
- `entity_type` の値で処理を分けるコードは `src` に無い。影響は表示だけである（タイムラインの詳細、CSV、ダイジェストのまとめ方）。

### 取り込みの経路

1. `collectors/events.py` の `normalize_event` が、pyVmomi のイベントを辞書にする。1 回の取得は、最大 100 ページ × 500 件（`events.py:61,80`）。
2. `plugins/builtin.py` の `_event` が、`EventInput` にする。
3. 外部プラグインの場合は、`plugins/wire.py` でワーカーとの間を直列化する（双方向）。
4. `plugins/runtime.py` の `_persist_batch` が、1 行ずつ `ON CONFLICT DO NOTHING`（`(vcenter_id, collector_id, vmware_key)`）で入れる。カーソルの保存と同じトランザクションである。

これとは別に、組み込みコレクタの登録が無いときだけ使う旧経路（`services/ingestion.py` の `ingest_events_for_vcenter`）がある。

- `on_conflict_do_nothing().returning(...)` は、SQLite（3.47.1、SQLAlchemy 2.0.48）で、新しく入った行だけを返す。ただし `rowcount` は常に `-1` になる。RETURNING を付けると、今の件数の計算（`runtime.py:266`、`ingestion.py:117` の `rowcount or 0`）は使えなくなる。
- 本番のイメージ（`python:3.12-slim-bookworm`）の SQLite は 3.40.1 で、`RETURNING` に要る 3.35 以上を満たす。
- SQLite の 1 文あたりのバインド変数の上限は 32766 である。子の行を 1 文で全部入れると、これを超えうる。
- 保持期間による削除は、`delete(EventRecord)` の一括削除である（`services/ingestion.py:181`）。SQLite でも、接続ごとに `PRAGMA foreign_keys=ON` を付けている（`db/session.py:25,36`）ので、子表の `ON DELETE CASCADE` が効く。vCenter を削除すると、events も CASCADE で消える。

### プラグイン API の慣例

- `EventInput` などに任意項目を足すときは、末尾に既定値付きで足し、パッケージの minor 版を上げる。`PLUGIN_API_VERSION = 1` は上げない（`packages/plugin-api/CHANGELOG.md`、`docs/development/collector-plugin-authoring.md`）。
- 入力の型は `@dataclass(frozen=True, slots=True)` で、パッケージの `__init__` から公開する（`EventInput` と同じ）。
- wire は `.get()` で読み、古いワーカーからの応答でも壊れないようにする（`plugins/wire.py:146-150`）。
- 長さの上限は `limits.py` に置き、`tests/test_plugin_api_limits_match_models.py` で DB の列と照合する。長すぎる名前は `limits.truncate()` で切り詰める（`collector-plugin-authoring.md:283`）。
- 検証の長さ超過は warning を出すだけである。PostgreSQL では、挿入のときに失敗する。
- テスト用の偽オブジェクト `FakeManagedObject`（`testing/_vmomi.py:34-48`）は `_wsdlName` を持たない。例のコレクタのテスト（`examples/example-event-collector/tests/test_power_event_collector.py:45,62,159-163`）は、これを `entity` に渡している。

## 2. 対象の取り出し方

### 公開する関数と型

plugin-api の `vmware.py`（`moid()` の隣）に置く。pyVmomi は import しない。

```python
@dataclass(frozen=True, slots=True)
class EventEntityInput:
    role: str
    position: int = 0
    entity_type: str | None = None
    entity_moid: str | None = None
    entity_name: str | None = None
    is_primary: bool = False


def event_entities(event: Any) -> tuple[EventEntityInput, ...]:
    """イベントの対象をすべて返す。空でなければ、is_primary が真のものがちょうど 1 つある。"""
```

`EventEntityInput` は、パッケージの `__init__` から公開する。本体の `normalize_event`、雛形（`scaffold.py`）、例のコレクタは、この関数を使う。同じ規則を 3 か所に書かない。戻り値の形は 1.6.0 で確定させ、1.7.0 では `EventInput` に項目を足すだけにする。

### 何を対象とみなすか

型の宣言ではなく、**値**で判定する。属性の一覧は、pyVmomi のイベントでは `_GetPropertyList()`、偽オブジェクトではインスタンスの属性の辞書から取る。属性の値（配列は要素ごと）が次のどれかなら、対象として集める。入れ子はたどらない（例外は下に挙げる 3 つだけ）。

1. **対象の引数**: 型名（`_wsdlName`、無ければクラス名の最後の `.` の後）が、次のどれかであるもの。
   - 参照を持つ引数: `ComputeResourceEventArgument`・`DatacenterEventArgument`・`DatastoreEventArgument`・`DvsEventArgument`・`FolderEventArgument`・`HostEventArgument`・`ManagedEntityEventArgument`・`NetworkEventArgument`・`ResourcePoolEventArgument`・`VmEventArgument`
   - 名前だけの引数: `EntityEventArgument`

   参照は、引数の中で `_moId` を持つ属性の値とする。参照が None の引数は、名前だけの対象として残す。名前も参照も無いものは捨てる。`AlarmEventArgument`・`ScheduledTaskEventArgument`・`ProfileEventArgument`・`RoleEventArgument` は、名前があっても対象にしない。
2. **管理対象そのもの**: `_moId` を持つ値。型が分かり、それが `ManagedEntity` の子クラス（1 章の 16 種類）でないものは除く。型が分からないものは、種別を NULL にして残す。「型が分かる」のは、`_wsdlName` を持つか、クラス名が `vim.` で始まるときだけである。`_wsdlName` の無い偽オブジェクト（`FakeManagedObject` を直接作ったものや `SimpleNamespace(_moId=...)`）は、型が分からないものとして残す。
3. **EventEx の `object`**: `objectId`・`objectType`・`objectName` から 1 件を作る。
   - `objectType` は、型なら `_wsdlName` を使い、文字列なら先頭の `vim.` を外す。16 種類に無い型名は除く。値が無ければ種別を NULL にする。
   - `objectId` が無く `objectName` だけがあるときは、名前だけの対象にする。
4. **入れ子の例外**（障害の調査で要るものだけ）
   - `hostOutOfSync`（`DvsHostWentOutOfSyncEvent`、`OutOfSyncDvsHost` は配列）: `.outOfSyncHost` を対象の引数として読む。役割は `hostOutOfSync`。
   - `connectee`（`DvsPortConnectedEvent` / `DvsPortDisconnectedEvent`）: `.connectedEntity` を管理対象として読む。役割は `connectee`。
   - `info`（`TaskEvent` / `TaskTimeoutEvent`）: `.entity` を管理対象として、`.entityName` を名前として読む。役割は `info.entity`。`info.locked[]` は読まない。

   ほかの入れ子（`permissions[].entity`、`hostSpec.host`、`configSpec.*`、`reason`、`fault` など）は読まない。

### 値の読み方

- 管理対象からは、`_moId` と `_wsdlName` だけを読む。`name` などの属性を `getattr` で読まない（読むと vCenter に問い合わせる）。偽オブジェクトの名前は、インスタンスの辞書（`vars(obj).get("name")`）からだけ読む。pyVmomi の参照は、そこに `name` を持たない。
- 引数（`*EventArgument`）の `name` は、データとして持っているので、そのまま読んでよい。
- 管理対象そのものの属性 `X` の名前は、イベントに文字列の属性 `XName` があれば、そこから取る（例: `referenceHost` と `referenceHostName`）。それでも無ければ、同じ moid の別の対象の名前を使う。
- 種別は `_wsdlName` を使う。無ければ、クラス名が `vim.` で始まるときだけ、その `vim.` を外したものを使う。それ以外は NULL にする（クラス名の `FakeManagedObject` などを種別にしない）。
- 名前は上限を超えれば `limits.truncate()` で切り詰める。moid と種別は、上限を超えれば NULL にする。どの場合も、対象は捨てない。

1 件の対象は、`EventEntityInput` の各項目を持つ。

| 項目 | 内容 |
|---|---|
| `role` | イベントの属性名。EventEx は `object`、入れ子の例外は上に書いた名前 |
| `position` | 配列の添字。配列でなければ 0 |
| `entity_type` | `HostSystem` の形。型の情報が無ければ NULL |
| `entity_moid` | `host-10` の形。参照が無ければ NULL |
| `entity_name` | 名前 |
| `is_primary` | 主な対象なら真 |

同じ moid が、複数の役割で入ることがある（例: アラームの `entity` と `host`、アラームの定義元の `source`）。子表を使う側（#1・#5）は、必要なら moid で重複を除く。

### 主な対象を選ぶ順

上から順に見て、最初に見つかったものを主な対象にする。

1. 明示された対象: `entity`、EventEx の `object`、ExtendedEvent の `managedObject`
2. `vm`
3. 子クラスが持つ対象と、入れ子の例外（`hostOutOfSync`・`info.entity`）。次の属性は除き、8 段目に回す。
   - 接頭辞が `source`・`src`・`old`・`prev`・`conflicted`・`dest`・`dst` のもの
   - `parent`・`newParent`・`connectee`

   3 段目の中は、次の順で選ぶ。この並びに無い属性は、属性名の辞書順で後ろに並べる。pyVmomi と偽オブジェクトでは属性の並びが違うので、並びには頼らない。

   `failedHost` → `isolatedHost` → `hostJoined` → `hostLeft` → `hostBackInSync` → `hostMember` → `hostOutOfSync` → `datastore` → `resourcePool` → `referenceHost` → `info.entity`

   `newDatastore`（`LockerReconfiguredEvent`）は除かない。新しい置き場所が主な対象になり、`oldDatastore` は 8 段目に回る。
4. `ds` → `net` → `dvs`
5. `host`
6. `computeResource`
7. `datacenter`
8. 3 段目で除いた属性（属性名の辞書順。ほかに何も無いときだけ）

同じ役割の配列（`hostOutOfSync[]` など）では、`position` が最小のものを選ぶ。

### 代表的なイベントの結果

「基底の属性」は、そのイベントの分類（`VmEvent`・`HostEvent`・`ClusterEvent`・`DvsEvent` など）で、通常、値が入るものを想定した。この表を、PR B のテストの期待値にする。

| イベント | 基底の属性 | 子クラスの属性 | 主な対象 |
|---|---|---|---|
| `HostConnectionLostEvent` | host・computeResource・datacenter | — | `host` |
| `VmPoweredOnEvent` | vm・host・computeResource・datacenter | — | `vm` |
| `VmMigratedEvent` / `DrsVmMigratedEvent` | vm・host・computeResource・datacenter | sourceHost・sourceDatastore・sourceDatacenter | `vm` |
| `VmBeingMigratedEvent` | vm・host・computeResource・datacenter | destHost・destDatastore・destDatacenter | `vm` |
| `VmPowerOffOnIsolationEvent` | vm・host・computeResource・datacenter | isolatedHost | `vm` |
| `MigrationHostErrorEvent` | vm・host・computeResource・datacenter | dstHost | `vm` |
| `DasHostFailedEvent` | computeResource・datacenter | failedHost | `failedHost` |
| `DasHostIsolatedEvent` | computeResource・datacenter | isolatedHost | `isolatedHost` |
| `DatastoreRemovedOnHostEvent` | host・computeResource・datacenter | datastore | `datastore` |
| `DatastoreFileMovedEvent` | datacenter | datastore・sourceDatastore | `datastore` |
| `ClusterCreatedEvent` | computeResource・datacenter | parent（フォルダ） | `computeResource` |
| `DatacenterCreatedEvent` | datacenter | parent（フォルダ） | `datacenter` |
| `DvsCreatedEvent` | dvs・datacenter | parent（フォルダ） | `dvs` |
| `DvsMergedEvent` | dvs・datacenter | sourceDvs・destinationDvs | `dvs` |
| `ResourcePoolCreatedEvent` | computeResource・datacenter | resourcePool・parent | `resourcePool` |
| `ResourcePoolMovedEvent` | computeResource・datacenter | resourcePool・oldParent・newParent | `resourcePool` |
| `DvsHostJoinedEvent` | dvs・datacenter | hostJoined | `hostJoined`（ホスト） |
| `DvsHostStatusUpdated` | dvs・datacenter | hostMember | `hostMember`（ホスト） |
| `DvsHostWentOutOfSyncEvent` | dvs・datacenter | hostOutOfSync（入れ子） | `hostOutOfSync`（ホスト） |
| `DvsPortConnectedEvent` | dvs・datacenter | connectee（入れ子） | `dvs` |
| `TaskEvent` | （タスクによる） | info.entity（入れ子） | `vm` があれば `vm`、無ければ `info.entity` |
| `HostWwnConflictEvent` | host・computeResource・datacenter | conflictedVms[]・conflictedHosts[] | `host` |
| `LockerReconfiguredEvent` | — | oldDatastore・newDatastore | `newDatastore` |
| `AlarmStatusChangedEvent` | （対象による） | entity・source | `entity` |
| `ScheduledTaskCompletedEvent` | （対象による） | entity | `entity` |
| `PermissionAddedEvent` | （対象による） | entity | `entity` |
| `ProfileReferenceHostChangedEvent` | — | referenceHost（管理対象そのもの。名前は `referenceHostName`） | `referenceHost` |
| `VmDeployFailedEvent` | vm・host・computeResource・datacenter | destDatastore（名前だけ） | `vm` |
| `EventEx` | （対象による） | object | `object` |
| `ExtendedEvent` | （対象による） | managedObject | `managedObject` |
| `DatacenterRenamedEvent` | datacenter | — | `datacenter` |

- DVS へのホストの参加・離脱・同期の復帰・状態の更新・同期の外れ（`DvsHostJoined` / `Left` / `BackInSync` / `StatusUpdated` / `WentOutOfSync`、`OutOfSyncDvsHost`）は、状態が変わったホストを主な対象にする。DVS は子表に残る。
- DVS のポートの接続と切断は、DVS を主な対象にする。つながった VM やホストは、子表に `connectee` として残る。`connectedEntity` は名前を持たず、このイベントの基底には `vm` が入らないので、`connectee` の名前は通常 NULL になる（moid と種別は入る）。
- 主な対象にならなかった対象も、すべて子表に入る（例: `VmMigratedEvent` の `host`・`sourceHost`・`sourceDatastore`・`computeResource`・`datacenter`）。

### 偽オブジェクト

テスト用の偽オブジェクト（`testing/_vmomi.py`）も直す。

- `fake_host`・`fake_vm`・`fake_datastore` などに `_wsdlName` を持たせる。
- 対象の引数を作るヘルパー `fake_event_argument(obj, *, name=None)` を足す。名前は `obj` の辞書の `name` を既定にする。`fake_event(..., host=fake_event_argument(fake_host()))` のように、既存の `**attributes` で渡す。引数の型名は、`obj` の `_wsdlName` から次の表で決める（pyVmomi を import しないので、表で持つ）。参照を持つ属性の名前も、pyVmomi の引数と同じにする。

| `obj` の `_wsdlName` | 引数の型名 | 参照の属性 |
|---|---|---|
| `HostSystem` | `HostEventArgument` | `host` |
| `VirtualMachine` | `VmEventArgument` | `vm` |
| `Datastore` | `DatastoreEventArgument` | `datastore` |
| `Network`・`DistributedVirtualPortgroup`・`OpaqueNetwork` | `NetworkEventArgument` | `network` |
| `DistributedVirtualSwitch`・`VmwareDistributedVirtualSwitch` | `DvsEventArgument` | `dvs` |
| `ComputeResource`・`ClusterComputeResource` | `ComputeResourceEventArgument` | `computeResource` |
| `ResourcePool`・`VirtualApp` | `ResourcePoolEventArgument` | `resourcePool` |
| `Datacenter` | `DatacenterEventArgument` | `datacenter` |
| `Folder`・`StoragePod` | `FolderEventArgument` | `folder` |
| それ以外（`ManagedEntity`、`_wsdlName` が無いもの） | `ManagedEntityEventArgument` | `entity` |
- 例のコレクタのテストのうち、意図と合わないもの（VM のイベントに `fake_host` を渡している `:45` など）は直す。

## 3. 保存の形

### events 表

- `entity_moid`（`String(256)`、NULL 可）を足す。索引は `ix_events_vcenter_id_entity_moid`（`(vcenter_id, entity_moid)`）。moid は vCenter の中でしか一意でないので、単独の索引にはしない。
- `entity_name`・`entity_type`・`entity_moid` は、`EventInput` の同名の項目から入れる。組み込みのコレクタは、`event_entities()` の主な対象の値を入れる。

### 子表 `event_entities`

| 列 | 型 | 内容 |
|---|---|---|
| `id` | Integer | 主キー |
| `event_id` | Integer | FK → `events.id`、`ON DELETE CASCADE` |
| `vcenter_id` | Uuid | moid で引くための非正規化。FK は張らない（削除は `event_id` の CASCADE で連動する） |
| `role` | String(64) | 役割 |
| `position` | Integer | 配列の添字。配列でなければ 0 |
| `is_primary` | Boolean | 主な対象なら真 |
| `entity_type` | String(256)、NULL 可 | `HostSystem` の形 |
| `entity_moid` | String(256)、NULL 可 | |
| `entity_name` | String(1024)、NULL 可 | |

- 一意制約は `uq_event_entities_event_id_role_position`（`(event_id, role, position)`）。先頭が `event_id` なので、`event_id` だけの索引は作らない。
- 索引は `ix_event_entities_vcenter_id_entity_moid`（`(vcenter_id, entity_moid)`）。
- 制約と索引の名前は、モデルと移行で同じにする（モデルと移行を照合するテストは無い）。
- 主な対象も `is_primary = true` で子表に入れる。子表だけで、そのイベントのすべての対象が分かる。
- 時間の範囲で引くときは、events と結合する（子表に `occurred_at` は持たない）。
- 長さの上限は `limits.py` に置き、照合テストに足す。役割は `MAX_EVENT_ENTITY_ROLE = 64` を新しく作る。moid は `MAX_ENTITY_MOID`（256）を使い、その注記（今はメトリクスだけを指す）を直す。名前は `MAX_ENTITY_NAME`（1024）、種別は `MAX_EVENT_ENTITY_TYPE`（256）を使う。

### 挿入

- events は、今と同じく 1 行ずつ入れる。events 専用の関数で `ON CONFLICT DO NOTHING ... RETURNING id` にし、返った `id` をその行のイベントに対応させる（1 行ずつなので、順序の問題は起きない）。メトリクスとログは、共通の `_insert_on_conflict_do_nothing` のまま変えない。
- 件数は、`id` が返った行の数で数える（`rowcount` は使わない）。
- 重複で捨てられたイベントには、子を足さない。同じバッチの中で同じ `vmware_key` が 2 回来たときは、先に入った方の子だけが入る。
- 子の行は、バッチの終わりに、新しく入ったイベントの分をまとめて入れる。文は、既存の `_insert_on_conflict_do_nothing` と同じく方言ごとの insert（`sqlalchemy.dialects.postgresql.insert` / `sqlalchemy.dialects.sqlite.insert`）で `on_conflict_do_nothing()` を付けて作る。行は `session.execute(stmt, rows)` の executemany の形で渡す（1 行ぶんの文を DBAPI の executemany で流すので、バインド変数の上限に当たらない）。全部の値を連ねた 1 文の INSERT にはしない。
- 子の行は、入れる前に本体の側で次のように整える。プラグインが不正な対象を送っても、バッチ全体が巻き戻り続けないようにするためである。
  - 名前は切り詰める。moid と種別は、上限を超えれば NULL にする。
  - 役割が空か上限を超える子は捨てる（warning を出す）。
  - `(role, position)` の重複は、先のものを残す。
  - `is_primary` が真の子が 0 件か 2 件以上なら、events の列と同じ moid（moid が無ければ同じ名前）の子のうち、2 章の「主な対象を選ぶ順」で最初に来るものを主な対象にし直す。当てはまる子が無ければ、すべて偽にする。この場合、子表に主な対象が無いイベントができる。子表を使う側（#1・#5）は、主な対象を events の列から取る。
- events の `entity_moid` も、上限を超えれば NULL にする。
- 旧経路（`services/ingestion.py`）も、同じ関数を使う。

### 削除と既存の行

- 保持期間の削除と vCenter の削除は、CASCADE で子表に連動する。子表の専用の削除処理は作らない。
- 保存済みの行は直さない。重複を捨てる挿入なので、後から埋まることもない。保持期間（`event_retention_days`、既定 7 日）が過ぎるまでは、新旧の `entity_type` の値が混ざる。

### 移行

- 1 本の移行で、`events.entity_moid` と索引、`event_entities` の表を作る。
- 列は「`inspect` して無ければ `op.add_column`」、表は「無ければ `create_table`」の形にする。head は実装のときに確かめ直す（本書の時点では `d7e8f9a0b1c2`）。
- downgrade は、`event_entities` を消し、索引を消してから `entity_moid` を消す（SQLite では、索引が残ったままでは列を消せない）。

## 4. プラグイン API

- **1.6.0（PR B）**
  - `EventEntityInput` と `event_entities()` を足す（2 章）。
  - 偽オブジェクトに型を持たせ、`fake_event_argument()` を足す。
- **1.7.0（PR C1）**
  - `EventInput` の末尾に、`entity_moid: str | None = None` と `entities: tuple[EventEntityInput, ...] = ()` を足す。
  - `limits.py` に `MAX_EVENT_ENTITY_ROLE` を足し、`MAX_ENTITY_MOID` の注記を直す。
  - 検証の warning を足す。対象は、長さ、`(role, position)` の重複、`entities` が空でないのに `is_primary` が真のものがちょうど 1 つでないこと。
  - wire の双方向に足し、`.get()` で読む。古いワーカーからの応答では、`entity_moid` が NULL、`entities` が空になる。
  - 照合テストに、events と子表の列を足す。
- events の列（`entity_name`・`entity_type`・`entity_moid`）は `EventInput` の項目から入れ、`entities` からは作らない。`entities` が空なら子表には何も入れず、events の列だけが埋まる（古いプラグインの今の動きと同じ）。
- 版を上げるたびに、本体（`pyproject.toml`）と例のコレクタ（`examples/example-event-collector/pyproject.toml:7`。今は `>=1.1.0`）の依存の下限を合わせ、ルートの `uv.lock` を作り直す。PyPI への公開は人手で行う。

## 5. API と画面

- `EventRead` に `entity_moid` を足す（`from_attributes` なので、列がそのまま出る）。
- フロントは、zod のスキーマ（`frontend/src/api/schemas/events.ts`）と CSV の列（`frontend/src/events/eventCsv.ts`・`eventRowToCsv.ts`）を足す。CSV のテストはヘッダーを文字列で比べているので、合わせて直す。
- 子表の内容を返す API と画面は、本書では作らない。使うのは #1・#5 である。
- チャット・ダイジェストの集約文脈には、保存したイベントの `entity_moid` や `event_entities` を含めない。メトリクスの `entity_moid` や、イベントのメッセージ・添付 CSV などの本文に現れる moid は、LLM の送信前に匿名化する（`services/llm/llm_anonymization.py`）。

## 6. PR の分け方

### PR B: 対象の取り出しと、主な対象の名前・種別

DB は変えない。

- plugin-api 1.6.0（2 章と 4 章）
- 本体の `normalize_event`、雛形、例のコレクタを、`event_entities()` の主な対象を使うように直す。
- 2 章の表をテストにする。本物の pyVmomi のイベントで確かめる（偽オブジェクトだけにしない）。スタブ付きの管理対象から名前を読まないこと（問い合わせが起きないこと）もテストにする。
- 依存の下限とルートの `uv.lock` を合わせる。
- 本体と plugin-api の CHANGELOG に、次のことを書く。
  - `entity_type` が `HostSystem` の形になる。
  - ホスト系などのイベントに、対象の名前が入る。
  - 保持期間が過ぎるまでは、新旧の値が混ざる。
- 文書: `docs/development/collector-plugin-authoring.md`、plugin-api の `README.md`

### PR C1: moid と子表の保存

- 移行（3 章）と、移行のテスト（`tests/test_db_session_migrations.py:269-325` が手本。downgrade と upgrade の往復も確かめる）
- plugin-api 1.7.0（4 章）
- 組み込みのコレクタの変換（`plugins/builtin.py:33` の `_event`）が、`entity_moid` と `entities` を渡すようにする。
- `_persist_batch` と旧経路を、3 章の挿入に変える。
- モックとシードの moid は、メトリクスの moid と揃える。
- PostgreSQL の CI のジョブ（`.github/workflows/ci.yml`。今は決まったテストしか流さない）に、子の挿入を通るテストを加える。
- 文書: `docs/features/features_list.md`（events 表の列）

### PR C2: API と画面

5 章のとおり。

## 7. 後続（本書の範囲外）

- 「影響の大きい対象」とタイムラインの絞り込みのキーを、名前から moid に替える。イベントは `HostSystem`、ログは `host` と、種別の表示が揺れる件も含む。
- 子表を使う機能（影響範囲マップ #1、既知の障害パターン #5）
- 入れ子の例外に挙げなかった対象（`permissions[].entity`、`hostSpec.host`、`configSpec.*` など）。必要になった機能で足す。
- `fake_event` の既定の種別名が、接頭辞の無い `VmPoweredOnEvent` である件

## 8. 確認方法

- PR B
  - 2 章の表のとおりに主な対象が選ばれることを、本物の pyVmomi のイベントで確かめる。
  - スタブ付きの管理対象で、名前の読み出しが起きないことを確かめる。
  - モックのモードでイベント一覧とタイムラインを開き、対象の名前と種別が表示されることを見る。
- PR C1: SQLite と PostgreSQL の両方で、次を確かめる。
  - 移行（upgrade と downgrade）
  - 子の挿入（バインド変数の上限を超える件数でも入ること）
  - 重複したイベントで、子が増えないこと
  - 保持期間の削除と vCenter の削除で、子も消えること
  - 取り込みの件数が正しいこと
  - 不正な対象（長すぎる値、役割の重複、主な対象が 0 件や 2 件）でも、バッチが失敗しないこと
- PR C2: API の応答と CSV に `entity_moid` が出ることを確かめる。

## 9. リスク

- **大きいバッチで遅くなる**: 子の行は、1 件のイベントにつき 3〜6 行になる。executemany でまとめて入れることで、文の数を抑える。
- **主な対象の選び方が、運用者の期待と違う型がある**: 2 章の表に無い型は、規則のとおりに決まる。気になる型が見つかれば、3 段目の順を直す。主でない対象は子表に残るので、情報は失わない。
- **プラグインの版の不一致**: 古い plugin-api のプラグインは、`entities` を送らない。その場合、子表には何も入らず、events の列だけが埋まる（今と同じ）。
- **vCenter への問い合わせ**: 管理対象の属性を誤って読むと、イベント 1 件ごとに vCenter に問い合わせ、失敗すれば取り込みが止まる。値の読み方（2 章）を守り、テストで確かめる。
- **将来の型**: インベントリの型は、pyVmomi 9.0.0.0 の 16 種類を固定の一覧で持つ。将来の版で `ManagedEntity` の子が増えると、その型の対象は捨てられる。pyVmomi を上げるときに一覧を確かめる。
