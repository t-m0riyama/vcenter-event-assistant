# 既知の障害パターンを検知する

最終更新: 2026-11-23（全 PR マージ済み）

[障害調査を楽にする機能 10 案](2026-11-22-troubleshooting-ideas.md)（以下「10 案」）の「案 5」にあたる。前提の「案 0a」（Issue #346）と「案 0b」（Issue #347）は済んでいる。

本書の用語は、[イベントの対象の計画書](2026-11-23-event-entities.md) に合わせる。vCenter の管理対象を一意に指す ID（`host-10` のような値）を **moid** と呼び、イベントが指す管理対象を **対象** と呼ぶ。`event_entities` の 1 行が持つ属性名（`host`・`vm`・`object` など）を **役割** と呼ぶ。コードの場所は、バックエンドを `src/vcenter_event_assistant/` から、画面を `frontend/src/` から書く。行番号は、本書を書いた時点の main のものである。

## 進捗

| PR | 内容 | 状態 |
|---|---|---|
| A | 本書 | マージ済み [PR #360](https://github.com/t-m0riyama/vcenter-event-assistant/pull/360) |
| B | 判定の処理と組み込みのパターン、パターンの一覧の API、タイムラインの API（`highlights.detected_patterns`） | マージ済み [PR #361](https://github.com/t-m0riyama/vcenter-event-assistant/pull/361) |
| C | タイムラインの画面（「検知した障害パターン」） | マージ済み [PR #362](https://github.com/t-m0riyama/vcenter-event-assistant/pull/362) |
| D | 通知（アラートルールの種類 `event_pattern`） | マージ済み [PR #363](https://github.com/t-m0riyama/vcenter-event-assistant/pull/363) |

各 PR は単独でマージでき、テストが通る状態にする。

## Context

イベントの重要度の判定（スコアルール、`rules/notable.py`、イベントスコアのアラートルール）は、どれもイベントを 1 件ずつ見る。そのため、次のような「並び」で初めて意味を持つ障害を見分けられない。

- ホストの切断が、短い間に何度も起きている。
- APD（All Paths Down）が始まり、そのままタイムアウトまで進んだ。
- HA がホストの障害を検知し、続いて VM を再起動した。

Issue #346 で EventEx の本当の種別（`esx.problem.*` など）が、Issue #347 で対象の moid と役割（`event_entities`）が保存されるようになった。そこで、同じ対象に起きた複数のイベントの並び（順序と時間幅）で、既知の障害パターンを判定する。

決めたこと（利用者の決定）:
- 結果は、まずタイムラインの「ハイライト」に出す（PR B・C）。続けて、アラートルールの新しい種類で通知する（PR D）。
- パターンの定義は、最初の版ではコードに同梱する固定の一覧にする。管理者が JSON で入れ替える機能は、定義の形が固まってから後続で足す。
- 判定の材料はイベントだけにする。リモートログは、moid を持たずホスト名の表記も揃わないので、10 案の「案 8」（ログのパターン集約）のあとに回す。
- パターンに使う種別の名前は、vCenter のイベントカタログと公開情報で確かめる（1 章）。

## 1. 前提（調べて分かったこと）

### イベントと対象の持ち方

- `events`（`db/models.py:44-74`）は、主な対象の `entity_moid`・`entity_name`・`entity_type` を持つ。索引は `(vcenter_id, occurred_at)`、`(vcenter_id, entity_moid)`、`event_type` 単独などである。`(event_type, occurred_at)` の複合索引は無い。
- `event_entities`（`db/models.py:77-94`）は、1 件のイベントのすべての対象を、役割・位置・種別・moid・名前で持つ。一意制約は `(event_id, role, position)`、索引は `(vcenter_id, entity_moid)`。
- 子表に行があるのは、PR #354 を適用した後に取り込んだイベントだけである。古い plugin-api のプラグインのイベントにも行は無い。
- 対象の取り出し（`packages/plugin-api/.../vmware.py` の `event_entities()`）を pyVmomi のイベントで確かめた結果は、次のとおりである。
  - EventEx に `objectId` があると、`object` の役割の行ができる（種別は `objectType` から）。基底の属性（`host`・`computeResource` など）に値があれば、それぞれの役割の行もできる。どちらが入るかはイベントの出し方による。
  - ExtendedEvent は、対象が `managedObject` の役割に入る。
  - `DasHostFailedEvent` の主な対象は `failedHost`、`VmRestartedOnAlternateHostEvent` と `VmFailedMigrateEvent` の主な対象は `vm` である。基底の属性があれば、どちらも `computeResource` の行を持つ。`VmRestartedOnAlternateHostEvent` は、障害ホストを `sourceHost` に持つ。
  - 同じ moid が、1 件のイベントの中で複数の役割に入ることがある（例: アラームの `entity` と `host`、EventEx の `object` と `host`）。
- ESXi が出す `esx.problem.*` の EventEx が、実機で `object` と基底の `host` のどちらを持つかは確かめていない（手元の DB に該当の行が無い）。そのため、ホストでまとめるパターンは、`host`・`object`・`managedObject` の役割のうち、種別が `HostSystem` のものを同じ対象とみなす（2 章）。
- デバイスやデータストアは、EventEx の `arguments` やメッセージにあり、子表には入らない。APD を LUN ごとに見分けることはできない。

### 種別の名前（確かめた結果）

登録済みの vCenter（8.x）から `scripts/dump_event_catalog.py` でイベントカタログ（2196 件）を読み、次を確かめた。

| 種別 | 確かめた方法 |
|---|---|
| `vim.event.HostConnectionLostEvent`・`vim.event.HostReconnectionFailedEvent` | カタログ |
| `vim.event.DasHostFailedEvent`・`com.vmware.vc.HA.DasHostFailedEvent` | カタログ |
| `com.vmware.vc.ha.VmRestartedByHAEvent`（`ha` は小文字）・`vim.event.VmRestartedOnAlternateHostEvent` | カタログ |
| `vim.event.VmFailedMigrateEvent` | カタログ |
| `esx.problem.storage.apd.start`・`esx.problem.storage.apd.timeout` | 公開情報（Broadcom の KB 406074・310620、Veeam の資料） |
| `esx.problem.net.vmnic.linkstate.down` | 公開情報（Broadcom の KB 424517、Veeam の資料） |

- 通常のイベントの種別は `vim.event.X` の形で保存される（`collectors/events.py:107-113`）。
- ESXi が出す `esx.problem.*` の多くは、vCenter のカタログに載っていない（ESXi の側の定義のため。カタログの `esx.*` は 93 件だけ）。
- 回復を表す `esx.clear.storage.apd.exit`・`esx.clear.net.vmnic.linkstate.up` も公開情報で確かめたが、使うのは「否定」のパターン（10 章）なので、最初の版では使わない。
- PDL（Permanent Device Loss）の種別は、カタログにも、確かな公開情報にも見つからなかった。最初の版には入れない。

### 今の仕組みとつなぐ場所

- **タイムラインのハイライト:** `IncidentTimelineHighlights`（`api/schemas/incident_timeline_view.py:208-211`）が `first_signal`・`top_entities`・`new_event_types` を持つ。組み立ては `_build_in_slot`（`services/incident_timeline_view.py:796-880`）で、同時実行の枠（`aggregation_slot`）の中で動く。
  - パターンの判定は、イベントの一覧とは別に問い合わせる。一覧は `min_score` で絞られ、子表の値を持たず、`item_limit` で切られるためである（イベントが行数の上限を超えると、一覧の取得は 422 になる。`_collect_events`）。
  - 期間は半開区間 `[from, to)` である（`_event_filters`）。
  - 保存したスナップショットは応答をそのまま持つ。項目は既定値付きで足すので、保存済みの結果も読める。
  - moid での絞り込み（PR #358）は、主な対象の `events.entity_moid` だけを見る。
- **アラート:**
  - ルールの種類は `Literal["event_score", "metric_threshold"]`（`api/schemas/alerts.py:14`）で、評価は種類ごとの関数を表で引く（`services/alerting/alert_eval.py:39-40`）。状態は `(rule_id, context_key)` で持つ。
  - イベントスコアのルールは、`alert_event_eval_lookback_hours`（`settings.py:482`）の範囲を見て、`context_key` にイベントの種別を入れる。クールダウン中に来た新しいイベントは `fired_at` に吸収し、通知しない。自動では解消しない。
  - 手での解消は `event_score` に限られる（`resolve_event_score_manually`、`alert_eval.py:128`。通知履歴の `can_resolve` と発火中の key の問い合わせ、`api/routes/alerts.py:197`・`:262`）。
  - タイムラインのアラートの収集（`_collect_alerts`、`services/incident_timeline_view.py:1034-1118`。`rule_type` ごとの絞り込みは 1067-1084 行と、後段の 1100-1107 行）は、vCenter・moid・名前の絞り込みを `rule_type` ごとに書いており、新しい種類は落ちる。行の組み立て（`_alert_entry`）にも、種類ごとの分岐がある。
  - 発火時の自動スナップショットの `trigger_id` は `String(128)`（`db/models.py:451`）で、`context_key` から作る（`services/incident_timeline_snapshot.py:23`）。
  - 画面: ルールの編集は `panels/settings/AlertRulesPanel.tsx`・`alertRuleDrafts.ts`・`alertRulesImportErrors.ts`、スキーマは `api/schemas/alerts.ts`、通知履歴は `panels/alerts/AlertHistoryPanel.tsx`。
- **LLM への受け渡し:** チャットに渡すタイムライン（`services/chat/chat_incident_timeline.py`）は画面のタイムラインとは別に作り、ハイライトを含まない。本書では、検知の結果を LLM に渡さない。

## 2. パターンの定義

### 形

`services/event_patterns/`（新設）に、変更できないデータクラスで持つ。

```python
@dataclass(frozen=True, slots=True)
class TargetRule:
    roles: frozenset[str]                # event_entities.role
    entity_types: frozenset[str]         # event_entities.entity_type（HostSystem など）


@dataclass(frozen=True, slots=True)
class PatternStep:
    event_types: frozenset[str]          # 完全一致


@dataclass(frozen=True, slots=True)
class EventPattern:
    id: str                              # 英小文字・数字・ハイフン、32 文字以内
    title: str                           # 画面と通知に出す名前（日本語）
    description: str                     # 何が起きているか、まず何を見るか（日本語）
    level: Literal["critical", "error", "warning"]
    kind: Literal["repeat", "sequence"]
    steps: tuple[PatternStep, ...]       # repeat は 1 つ、sequence は 2 つ以上
    target: TargetRule                   # 同じ対象とみなす子表の行
    within_minutes: int
    min_count: int | None = None         # repeat だけ。2 以上
    collapse_seconds: int = 0            # repeat だけ。同じ対象で、この秒数以内に続いたイベントは 1 回と数える
```

- **同じ対象:** そのイベントの `event_entities` のうち、役割が `target.roles` に、種別が `target.entity_types` に入る行の `(vcenter_id, entity_moid)`。moid が NULL か空の行は使わない。1 件のイベントが同じ moid を複数の役割で持つときは、1 回と数える。1 件のイベントが別々の moid を持つときは、それぞれの対象の材料になる。
- **repeat:** 同じ対象で、`steps[0]` の種別のイベントが、幅 `within_minutes` の窓の中に `min_count` 回以上起きた。`within_minutes` は窓の幅であり、検知の長さではない（重なる窓はつなぐので、検知は窓より長くなり得る）。
- **sequence:** 同じ対象で、`steps` の種別のイベントがこの順に起き、起点から最後の段の最初のイベントまでが `within_minutes` 以内である。
- 「否定」（例: 「APD が始まり、時間内に終わらなかった」）は最初の版では扱わない。判定に「今」と状態が要るためである。

定義の一覧は、テストで次を確かめる。
- `id` の一意性と形
- 種類と `steps`・`min_count`・`collapse_seconds` の組み合わせ
- `within_minutes` が 1 以上、24 時間（1440 分）以下
- 種別の名前、役割、種別の集合が空でないこと

### 組み込みのパターン（最初の版）

「ホスト」は、`TargetRule(roles={"host", "object", "managedObject"}, entity_types={"HostSystem"})` を表す。

| id | 名前 | 種類 | 種別 | 同じ対象 | 時間幅 | 回数 | まとめ | レベル |
|---|---|---|---|---|---|---|---|---|
| `host-conn-flapping` | ホストの切断の繰り返し | repeat | `vim.event.HostConnectionLostEvent` | ホスト | 60 分 | 3 | 0 秒 | error |
| `host-reconnect-failed` | ホストの切断後の再接続の失敗 | sequence | ① `vim.event.HostConnectionLostEvent` ② `vim.event.HostReconnectionFailedEvent` | ホスト | 30 分 | — | — | error |
| `apd-timeout` | APD のタイムアウト | sequence | ① `esx.problem.storage.apd.start` ② `esx.problem.storage.apd.timeout` | ホスト | 10 分 | — | — | critical |
| `apd-repeated` | APD の繰り返し | repeat | `esx.problem.storage.apd.start` | ホスト | 60 分 | 2 | 120 秒 | error |
| `nic-link-flapping` | NIC のリンクの不安定 | repeat | `esx.problem.net.vmnic.linkstate.down` | ホスト | 30 分 | 3 | 60 秒 | warning |
| `ha-failover` | HA によるフェイルオーバー | sequence | ① `vim.event.DasHostFailedEvent`・`com.vmware.vc.HA.DasHostFailedEvent` ② `com.vmware.vc.ha.VmRestartedByHAEvent`・`vim.event.VmRestartedOnAlternateHostEvent` | クラスタ（`roles={"computeResource"}`、`entity_types={"ClusterComputeResource"}`） | 30 分 | — | — | critical |
| `vmotion-failures` | vMotion の連続失敗 | repeat | `vim.event.VmFailedMigrateEvent` | ホスト | 60 分 | 3 | 0 秒 | warning |

- **まとめ（`collapse_seconds`）:** 1 回の障害で、同じ種別のイベントが同時に複数出るものを 1 回と数える。
  - APD の開始はデバイス（LUN）ごとに出る。2 つの LUN が同時にパスを失っても、1 回と数える。
  - NIC のリンクダウンは vmnic ごとに出る。スイッチの再起動で複数の vmnic が同時に落ちても、1 回と数える。
- `nic-link-flapping` は、`esx.problem.net.dvport.redundancy.lost` を数えない。リンクダウン 1 回に伴って出るので、二重に数えるためである。
- `vmotion-failures` は、`VmFailedMigrateEvent` だけを数える。失敗 1 回に `Migration*ErrorEvent` が伴うと、二重に数えるためである。
- APD のタイムアウトの既定は 140 秒なので、10 分あれば足りる。
- `description` には、まず見るものを書く。例: APD なら、同じ時間帯のほかのホストの APD とストレージのパス。HA なら、再起動した VM と障害ホストの状態。文面は PR B で書き、レビューする。
- 値（回数・時間幅・まとめ・レベル）は、運用で直せるようにはしない（固定の一覧のため）。直す必要が出たら、JSON での入れ替え（10 章）で扱う。

## 3. 判定

### 範囲

- タイムラインの要求の期間を `[from, to)` とすると、パターンごとに `[from - within_minutes, to)` のイベントを読む。
- 検知に使ったイベントのうち、少なくとも 1 件が `[from, to)` に入る検知だけを返す。
- 範囲より前に続く並びは、`from - within_minutes` より前の分を含まない。そのため、長く続く並びの `first_utc` と `event_count` は、要求の `from` によって変わる。repeat のまとめ（`collapse_seconds`）は最初に数えたイベントを基点に連鎖するので、検知の有無も `from` によって変わり得る。どれも仕様とする（同じ要求なら同じ結果になる）。
  - まとめを「直前に数えたイベントとの差」で比べるのは、「直前のイベントとの差」で比べると、間隔の短い不安定（例: 30 秒おきのリンクダウン）が 1 回にまとまり、検知できなくなるためである。
- 通知（PR D）も、同じ関数で範囲を求める（6 章）。

### 問い合わせ

パターンごとに、次の 1 本の SELECT で材料を読む。

- `events` と `event_entities` を `event_id` で結合する。
- 条件:
  - `events.event_type IN (パターンの種別)`
  - `events.occurred_at` が範囲に入る
  - `event_entities.role IN (target.roles)`、`event_entities.entity_type IN (target.entity_types)`
  - `event_entities.entity_moid` が NULL でも空でもない
  - vCenter を指定したときは `events.vcenter_id`。moid を指定したときは `event_entities.entity_moid`（4 章）
- 読む列: イベントの `id`・`vcenter_id`・`occurred_at`・`event_type`、子表の `entity_moid`・`entity_name`・`entity_type`。
- 並び: `(event_entities.vcenter_id, entity_moid, occurred_at, events.id)`。同じイベントと moid の子表の行が複数あれば、名前と種別のある行を優先する。同順位では子表の ID の小さい行を使う。
- **行数の上限:** 1 パターンあたり、子表の結合の結果を 10,000 行までにする（定数。`context_aggregation_max_rows` とは別）。超えたら、そのパターンは判定しない。タイムラインでは `omitted_patterns` に入れ、通知では警告をログに残す。
- **索引:** 結合には一意制約 `(event_id, role, position)` の先頭の列が効く。`events` は `(event_type, occurred_at)` の複合索引で種別と期間を絞れる。
- 同じ種別を使うパターン（切断、APD の開始）は、同じ行を 2 回読む。種別で絞るので行数は少ない見込みであり、最初の版ではまとめない。

PR B では `(event_type, occurred_at)` の複合索引を追加する。SQLite 3.47.1 で、統計を作らず 20 万件のデータを 50 日間の範囲で調べたところ、vCenter を指定したときに `ix_events_vcenter_id_occurred_at` が選ばれ、期間内のその vCenter の全イベントを読んだ。`ha-failover` の問い合わせは約 0.2 ms から約 50 ms に延びた。moid を指定すると vCenter の指定も必須になるため、SQLite の問い合わせは `INDEXED BY ix_events_event_type_occurred_at` で複合索引に固定する。PostgreSQL の索引選択はプランナーに任せ、問い合わせと移行は CI の PostgreSQL ジョブで確認する。

### 判定の手順（純関数）

DB を読まない純関数に分け、単体テストで固める。入力は、対象ごとに `(occurred_at, event_id)` の昇順に並んだイベントである。イベントの順序は、つねにこの組の辞書順で決める。時間幅はすべて閉区間（ちょうどを含む）にする。

同じ時刻のイベントの前後は、取り込んだ順（`events.id`）で決まる。vCenter の上の発生順と逆になることがあるが、同じ時刻のイベントでは区別しない（最初の版の制約）。

**repeat**

1. **まとめ:** `collapse_seconds` が 1 以上のとき、先頭から見て、直前に「数えた」イベントとの差が `collapse_seconds` 以内のイベントは、数えずに直前の回に含める。`collapse_seconds` が 0 ならまとめない（同じ時刻のイベントも別々に数える）。数えたイベントの並びを `c_1 … c_n` とする。
2. **窓:** 各 `j` について、`t(c_j) - t(c_i) ≤ within_minutes` となる最小の `i` を取る。`j - i + 1 ≥ min_count` なら、`c_i … c_j` に印を付ける。
3. **つなぐ:** 印の付いた区間 `[i, j]` のうち、共有するイベントがあるものをつなぎ、1 件の検知にする。
4. 検知に使ったイベントは、つないだ区間の `c` と、それぞれに含めたまとめのイベントである。

例（`min_count=3`、`within=60 分`、`collapse=0`）:
- 0・20・40 分 → 1 件（0〜40 分）
- 0・20・40・70・90 分 → 1 件（0〜90 分。`[0,40]`・`[20,70]`・`[40,90]` がつながる）
- 0・20・61 分 → 検知なし（61 - 0 > 60）
- 0・30・60 分 → 1 件（60 - 0 = 60 は含む）

**sequence**

1. 段 1 の種別のイベントを、順に起点の候補にする。
2. 起点のあとの段 2 の種別のイベントのうち、最初のものを選ぶ。段 3 以降も同じく、直前に選んだイベントのあとから探す（同じ時刻なら id が大きいもの）。
3. 最後の段の最初のイベントが、起点から `within_minutes` 以内なら、検知とする。最後の段は、直前の段に選んだイベントより後で、起点から `within_minutes` 以内の、最後の段の種別のイベントをすべて含める（HA で再起動した VM が分かるように）。`event_count` は VM の台数ではない（1 台につき 2 つの種別が両方出ることがある）。
4. 段がそろわないか、時間幅を超えたら、その起点は失敗とし、次の段 1 のイベントを起点にして探し直す。
5. 検知したら、検知に使った最後のイベントのあとから、次の起点を探す（検知どうしは重ならない）。検知の間にあった段 1 のイベントは、起点の候補にしない。

例（`within=30 分`）:
- A@0・A@25・B@40 → 1 件（A@25〜B@40）。A@0 は B@40 まで 40 分なので失敗し、A@25 で探し直す。
- A@0・B@30 → 1 件（30 分ちょうどは含む）。
- B@0・A@10 → 検知なし（順序が逆）。
- 同じ時刻の A（id=2）と B（id=1）→ 検知なし（B は A より前）。

### 1 件の検知

| 項目 | 内容 |
|---|---|
| `pattern_id`・`title`・`description`・`level` | パターンの定義から |
| `vcenter_id`・`vcenter_name` | 対象の vCenter。名前は `VCenter` の表から引く |
| `entity_moid` | 同じ対象の moid |
| `entity_name`・`entity_type` | 検知に使ったイベントのうち、最も新しい行の子表の値。名前が無ければ NULL |
| `first_utc`・`last_utc` | 検知に使った最初と最後のイベントの時刻 |
| `event_count` | 検知に使ったイベントの数（まとめたものを含む） |
| `event_ids` | 検知に使ったイベントの id。時刻順の最初の 20 件 |

## 4. タイムラインの API（PR B）

- `IncidentTimelineHighlights` に次を足す。どれも既定値付きにし、保存済みの結果も読めるようにする。
  - `detected_patterns: list[IncidentTimelineDetectedPattern] = []`
  - `detected_patterns_total: int = 0`（上限で切る前の件数）
  - `omitted_patterns: list[str] = []`（行数の上限で判定しなかったパターンの id）
- 判定するのは、要求の `sources` に `event` が入るときだけである。判定は `_build_in_slot` の中、同時実行の枠の中で行う。
- 要求の条件は、次のように当てる。
  - **期間・vCenter:** 3 章の範囲と問い合わせの条件にする。
  - **`entity_moid`（PR #358）:** 問い合わせの条件にする（`event_entities.entity_moid`）。このとき `entity` は当てない（アラートの収集と同じ規則）。
  - **`entity` だけ（名前の部分一致）:** 判定の後で、検知の `entity_name` に、今の部分一致と同じ規則で当てる。名前が無い検知は外れる。
  - **`min_score`:** 当てない（スコアはイベント 1 件の重要度で、パターンとは別の尺度のため）。
- 並べ方: レベル（critical → error → warning）、`last_utc` の新しい順、`pattern_id`、vCenter、moid。最大 20 件にする。
- **パターンの一覧の API:** `GET /api/event-patterns`（viewer 以上、読み取り専用）で、組み込みの定義（id・名前・説明・レベル・種類・種別・時間幅・回数）を返す。PR C の説明の表示と PR D のルールの編集で使う。
- 画面は、単独でマージしても壊れないよう、zod のスキーマに 3 つの項目を `.default(...)` 付きで足すだけにする。

## 5. タイムラインの画面（PR C）

- 「ハイライト」に「検知した障害パターン」を足す（`panels/timeline/TimelineHighlights.tsx`）。
  - 1 件ごとに、名前・レベルの印・対象（名前、無ければ moid）・vCenter・期間（`first_utc` 〜 `last_utc`）・件数を出す。
  - 説明（`description`）は、折りたたみで出す。
  - 「ここを起点にする」は、期間の設定を変えずに `first_utc` を起点にする。今の行の操作と同じように、条件バーで起点の前後 15 分・1 時間・6 時間から期間を選べる。期間より前から始まった検知は、期間を選び直すと全体を調べられる。
  - 0 件なら、この欄を出さない。`detected_patterns_total` が 20 を超えれば、残りの件数を出す。`omitted_patterns` があれば、「件数が多すぎるため判定しなかったパターンがあります」と出す。このときだけ `GET /api/event-patterns` を 1 回呼び、判定しなかったパターンの名前を出す。名前を取得できないときは id を出す。
- 「この対象で絞る」は付けない。タイムラインの moid での絞り込みは主な対象だけを見るので、検知に使ったイベントが一覧に出ない場合があるためである。
  - 例: `ha-failover` の対象はクラスタだが、イベントの主な対象は障害ホストと VM である。`vmotion-failures` の対象はホストだが、主な対象は VM である。
  - 絞り込みを子表（`event_entities`）の対象でも行うかは、後続で決める（10 章）。
- 検知に使ったイベントの印は一覧に付けない。まとめた行には代表のイベントの id だけが入り、検知の `event_ids` も先頭の 20 件までなので、どの行が検知に使われたかを正しく対応づけられないためである。
- 文書: `docs/userguide/timeline.md`（パターンの一覧、判定の規則、子表の無い古いイベントは判定に入らないこと、「この対象で絞る」が無い理由）、CHANGELOG。

## 6. 通知（PR D）

### ルール

- アラートルールの種類に `event_pattern` を足す。
  - 設定: `{"pattern_ids": [...], "cooldown_minutes": 10}`。`pattern_ids` が空なら、すべてのパターンを対象にする（あとで足したパターンも含む）。この規則を文書に書く。
  - 作成・更新（PATCH）・取り込みのどれでも、知らない id は 422 にする（今の PATCH は config を検証しないので、検証を足す）。評価のときに知らない id があれば、警告をログに残して飛ばす（将来パターンを消したとき）。
  - 通知のレベルは、ルールの `alert_level` にする（ほかの種類と同じ）。パターンの `level` は本文に書く。
- 判定の範囲: `[now - lookback - within_minutes, now)` を読み、検知に使ったイベントの少なくとも 1 件が `[now - lookback, now)` に入る検知を使う（3 章と同じ関数）。`lookback` は `alert_event_eval_lookback_hours`。
- `context_key`: `{vcenter_id}:{entity_moid}:{pattern_id}`。vCenter を先頭にし、今の vCenter での前方一致の絞り込みに乗せる。`metric_threshold` の key（`{vcenter_id}:{entity_moid}`）とは、どこでも `rule_type` で分けて解析しているので、ぶつからない。
  - 分け方: 最初の `:` の前を vCenter、最後の `:` の後を pattern_id、その間を moid とする（moid が `:` を含んでも分けられる。pattern_id は `:` を含まない）。

### 発火・再通知・解消

- 検知ごとの「時刻」は `last_utc` とする。同じ key の検知が範囲に複数あれば、`last_utc` が最も新しいものを使う。
- 状態の `fired_at` には、直近に通知した（または吸収した）検知の `last_utc` を持つ。解消しても `fired_at` は消さない。
- 発火と再通知は、イベントスコアの判定（`event_score_should_notify`）を流用せず、`event_pattern` 用の判定にする。流用すると、解消済みの状態では `fired_at` と比べずに通知するので、手で解消した直後の評価で同じ検知がまた発火するためである。
  - 状態が無いとき: 通知する。
  - 解消済みのとき: `last_utc` が `fired_at` より新しいときだけ通知する。
  - 発火中のとき: `last_utc` が `fired_at` より新しく、クールダウンを過ぎていれば再通知する。クールダウン中に `last_utc` が伸びたら、`fired_at` に吸収して通知しない。
  - そのため、切断の繰り返しのように並びが続いている間は、クールダウンごとに再通知される。続いていることを知らせるためで、仕様とする。
- 解消:
  - 判定したパターンで、範囲の中にその key の検知が無くなったら、通知せずに解消する。
    - イベントスコアのルールと違い、自動で解消する。key がパターン × vCenter × moid ごとにでき、発火中の状態が積み上がるためである。
    - 解消の通知はしない。パターンの終わりは、障害の回復を意味しないためである。
  - 判定しなかったパターン（行数の上限を超えたもの、評価のときに知らない id）の key は、状態を変えない。上限を超えるのはイベントが大量に出たときなので、その場面で黙って解消し、上限を下回ったときに一斉に発火し直すのを避けるためである。
  - ルールの `pattern_ids` から外したパターンの発火中の key は、次の評価で、通知せずに解消する。
  - 手でも解消できるようにする。手での解消の処理（`alert_eval.py:128`）、通知履歴の `can_resolve` と発火中の key の問い合わせ（`api/routes/alerts.py:197`・`:262`）、画面の解消ボタンの条件を `event_pattern` に広げる。解消の文言も種類に合わせる。手での解消は、今の処理のまま回復の通知を出す（利用者が操作したことを残すため）。
- 通知の本文: パターンの名前とレベル、対象（名前と moid）、vCenter、期間、件数、説明。

### つなぐ場所

- **通知履歴の応答（`AlertHistoryRead`）:** `event_pattern` の `context_key` から `vcenter_id`・`entity_moid` を取り出す。DB の移行は行わない。`(vcenter_id, entity_moid)` ごとに、`event_entities` の最新の行（`events.occurred_at` の降順、同時刻は `events.id` の降順）から `entity_name` を引く。一覧では組をまとめて問い合わせる。保持期間を過ぎるなどして名前を引けない場合は `None` とする。通知の本文には通知時点の名前を入れる。
- **タイムラインのアラートの行:** `_collect_alerts` と `_alert_entry` に `event_pattern` の分岐を足す。
  - vCenter だけで絞ると、`context_key` が `{vcenter_id}:` で始まるものを含める。
  - vCenter と moid で絞ると、組み込みのすべての pattern_id で作った key（`{vcenter_id}:{entity_moid}:{pattern_id}`）の IN で含める。前方一致にしないのは、`:` を含む moid（`a` と `a:b`）を取り違えないためである。
  - 前方一致には `autoescape=True` を付ける（今の metric と同じ）。
  - 後段の絞り込み（1100-1107 行）と名前の絞り込みにも分岐を足す。名前は通知履歴と同じ最新の行から解決する。名前が無ければ、`entity` で名前を絞るときに外れる。
  - 行に `vcenter_id`・`entity_moid`・説明を入れる。
- **自動スナップショット:** `trigger_id` は `context_key` から作られる。moid は最大 256 文字なので、`String(128)` を超え得る。`format_alert_rule_trigger_id` の結果が 128 文字を超える場合は、生成した値の先頭 111 文字に `_` と、元の `context_key` の SHA-256 の先頭 16 桁（16 進）をつなぐ。128 文字以内の値は従来どおりとする。自動スナップショットは、ハイライトを持たない要求で作るので、検知の結果は入らない。
- **画面:**
  - `api/schemas/alerts.ts` の `rule_type` の `z.enum`（2 か所）
  - `AlertRulesPanel.tsx`: 種類の選択と表示名（今は event_score 以外を「メトリクス閾値」と出す）、パターンの複数選択、クールダウンの編集（今は event_score だけ）
  - `alertRuleDrafts.ts`・`alertRulesImportErrors.ts`: 下書きと取り込みの検証
  - `AlertHistoryPanel.tsx`: 「タイムラインで見る」は、vCenter と発生時刻の前後だけを渡し、moid は渡さない（5 章と同じ理由。`ha-failover` の対象はクラスタで、moid で絞ると HA のイベントが一覧から消える）。解消ボタン
- 文書: `docs/userguide/alerts.md`、`docs/development/backend.md`、CHANGELOG。

## 7. PR の分け方

### PR A: 本書

- 本書を足す。
- [タイムラインの対象の計画書](2026-11-23-timeline-entity-moid.md) の進捗の表を直す（PR C をマージ済みにする）。

### PR B: 判定とタイムラインの API

- `services/event_patterns/` に、定義の型、組み込みの一覧、判定の純関数、問い合わせを置く。
- `GET /api/event-patterns` を足す。
- `_build_in_slot` から呼び、`highlights.detected_patterns`・`detected_patterns_total`・`omitted_patterns` を返す。
- 画面: zod のスキーマに 3 つの項目と、パターンの一覧の型を足す。
- テスト:
  - 定義の一覧の検証（2 章）
  - 純関数: 3 章の例をすべて。加えて、repeat のまとめ（`collapse_seconds` の境界）、sequence の最後の段の複数のイベント、同じ moid の複数の役割、1 件のイベントが別々の moid を持つ場合
  - 問い合わせ: 子表の無いイベント、moid が NULL か空の行、種別の条件（`HostSystem` 以外の `object`）、ほかの vCenter、範囲の前から始まった検知、範囲の端（`to` ちょうどは入らない）、行数の上限
  - API: 7 つのパターンがそれぞれ当たること、`entity_moid`・`entity`・`sources` の条件、並べ方と 20 件の上限と総数、保存済みの結果（項目の無い JSON）が読めること、パターンの一覧の API
  - EventEx の形の違い: `objectId` だけの EventEx、基底の `host` だけの EventEx、ExtendedEvent（`managedObject`）のどれでも、ホストでまとめるパターンが当たること（pyVmomi のイベントから `event_entities()` で子表の行を作る）。`objectType` の無い EventEx（`object` の行の種別が NULL）の扱いは、PR B の初めに決めてテストにする（9 章）
  - SQLite と PostgreSQL の両方で、問い合わせが通ること（`tests/services/test_aggregation_dialects.py` に倣い、CI の `auth-postgres` のジョブに `-k` で足す）
- 開発用のデータ: 少なくとも 1 つのパターンが当たるイベント（本物の種別の名前と子表の行）を足す。今のモックの種別は `vim.event.MockDemo*` で、どのパターンにも当たらない。
  - モック: `mocks/mock_collectors.py`
  - シード: `dev/mock_mode_seed.py`、`dev/screenshot_e2e_seed.py`
  - 文書: `docs/userguide/mock-mode.md`
- 文書: `docs/development/backend.md`（応答の項目、パターンの一覧の API）、CHANGELOG。

### PR C: タイムラインの画面

5 章のとおり。vitest のテストを足す。画面のスクリーンショットを PR に添える。

### PR D: 通知

6 章のとおり。通知履歴とタイムラインの対象名は、保持されている最新のイベントの子表からまとめて引く。DB の移行は行わない。発火時の `trigger_id` が 128 文字を超える場合は、先頭を残し、末尾に元の `context_key` の SHA-256 の先頭 16 桁を使う。

モックのモードに障害パターンのルールを 1 件加え、PR B で加えた切断の繰り返しで発火することをテストする。

## 8. 確認方法

- PR B
  - 組み込みの 7 つのパターンが、それぞれ本物の種別の名前と子表の行で当たること。当たらない並び（回数が足りない、順序が逆、時間幅を超える、別の対象、別の vCenter、`HostSystem` 以外の対象）では当たらないこと。
  - 3 章の例のとおりの結果になること。同じ入力なら、結果と並びが変わらないこと。
  - 同時に出た APD の開始（2 つの LUN）や NIC のリンクダウンが、1 回と数えられること。
  - 子表の無い古いイベントが、判定に入らないこと。
  - 期間の前から始まった並びが、期間の中のイベントがあれば検知されること。
  - 行数の上限を超えたパターンが `omitted_patterns` に入り、ほかのパターンは判定されること。
  - SQLite と PostgreSQL の両方で通ること。
- PR C
  - 検知が無いと欄が出ないこと。検知があると、名前・対象・期間・件数・説明が出ること。
  - 「ここを起点にする」で、起点が `first_utc` になること。
  - 総数が 20 を超えると残りの件数が、判定しなかったパターンがあるとその旨が出ること。
- PR D
  - 検知で発火し、クールダウン中は再通知しないこと。並びが続けば、クールダウンの後に再通知すること。
  - 検知が範囲から無くなると、通知せずに解消すること。手でも解消でき、解消のあと、同じ検知（同じ `last_utc`）では再発火しないこと。新しいイベントで検知が伸びれば再発火すること。
  - 行数の上限を超えたパターンの発火中の key が、解消されないこと。`pattern_ids` から外したパターンの key が、通知せずに解消されること。
  - `pattern_ids` で対象のパターンを絞れること。知らない id が、作成・更新・取り込みのどれでも 422 になること。
  - 通知履歴とタイムラインのアラートの行に、対象の vCenter と moid が出ること。vCenter と moid で絞ったタイムラインに、その通知の行が出ること。
  - 長い moid でも、自動スナップショットが保存されること。

## 9. リスク

- **実際のイベントで役割が想定と違う:** `esx.problem.*` と `com.vmware.vc.HA.*` のイベントが、実機でどの役割を持つかは確かめていない（手元の DB に該当の行が無い）。ホストでまとめるパターンは `host`・`object`・`managedObject` を見るので、どちらの形でも当たる見込みである。HA のパターンは、イベントに `computeResource`（クラスタ）が入らないと当たらない。実際のイベントで当たらないことが分かったら、コードの修正で役割の集合を直す。
- **`object` の行の種別が NULL:** `event_entities()` は、EventEx に `objectType` が無いと `object` の行の種別を NULL にする（`vmware.py:288-294`）。ESXi の EventEx が `objectId` だけを持つと、種別の条件（`HostSystem`）で外れ、基底の `host` も無ければ、ホストのパターンが当たらない。PR B では、役割が `object` で種別が NULL の行は、moid が `host-` で始まるときに限り `HostSystem` とみなしてホストのパターンの材料にする。
  ホストとみなすのは判定のときだけで、応答の `entity_type` は選ばれた子表の行の値を返す（その行の種別が NULL なら応答も NULL）。
- **1 回の障害で回数を超える:** 同時に出る同じ種別のイベントは、`collapse_seconds` でまとめる。まとめの幅より間を空けて出るイベントは、別の回と数える。実機で誤って当たる例が見つかったら、幅を直す。
- **データストアの障害が全ホストに及ぶ:** ホストごとに検知が出て、上限の 20 件を埋め得る。総数を返すので、切れたことは分かる。データストアでまとめるのは、10 案の「案 1」（影響範囲マップ）のあとにする。
- **古いイベント:** 子表の無いイベントは判定に入らない。保持期間（既定 7 日）を過ぎれば、古い行は無くなる。
- **判定の重さ:** タイムラインを開くたびに、パターンの数だけ問い合わせる。種別で絞るので行数は少ない見込みだが、行数の上限で守る。重ければ、判定の結果を保存する表を作る（後続）。
- **同じ障害が複数の検知になる:** たとえば APD のタイムアウトと APD の繰り返しは、同じ並びで両方当たり得る。最初の版では、どちらも出す（別の情報なので）。
- **クラスタでまとめるパターン:** `ha-failover` は、障害ホストと再起動した VM を、同じクラスタであることだけで結ぶ。同じクラスタで、同じ時間帯に別の理由で VM が再起動しても当たる。`VmRestartedOnAlternateHostEvent` は障害ホストを `sourceHost` に持つが、`com.vmware.vc.ha.VmRestartedByHAEvent` が持つかは確かめていないので、最初の版ではクラスタで結ぶ。

## 10. 範囲外（後続）

- 管理者が JSON でパターンを入れ替えること（イベント種別ガイドと同じ `format`・`version` の形の取り込みと書き出し）
- 「否定」のパターン（例: APD が時間内に終わらない、切断のあと再接続しない）
- PDL など、種別の名前を確かめられなかったパターン（PDL は Issue #398 の [計画書](2026-11-27-pdl-pattern.md) で扱う）
- 段ごとに同じ対象の役割を変えること（例: HA の障害ホストと、再起動のイベントの `sourceHost` で結ぶ）
- タイムラインの対象での絞り込みを、子表の対象でも行うこと（検知から「この対象で絞る」を付けるため）
- リモートログを材料に使うこと（10 案の「案 8」のあと）
- クラスタやデータストアの構成でまとめること（10 案の「案 1」のあと）。タスクの結果（「案 3a」）や発生中のアラーム（「案 3b」）を材料に使うこと
- 検知の結果を保存する表と、検知の一覧の画面
- 検知の結果をチャットやダイジェストに渡すこと。渡すときは moid を含むので、LLM への匿名化（PR #356）を通す。
