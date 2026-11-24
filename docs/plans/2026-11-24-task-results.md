# 完了したタスクの結果と所要時間を取り込む

最終更新: 2026-11-25（全 PR マージ済み）

[障害調査を楽にする機能 10 案](2026-11-22-troubleshooting-ideas.md)（以下「10 案」）の「案 3a」にあたる。ほかの案を前提にしない。「案 5」（[既知の障害パターン](2026-11-23-event-patterns.md)）は、本書で入るタスクの失敗を判定の材料にできるようになる（後続）。

本書では、vCenter のタスク（VM の電源操作や vMotion など、利用者やシステムが起こした操作の単位）のうち、成功・失敗・キャンセルのどれかで終わったものを **完了したタスク** と呼ぶ。vCenter の管理対象を一意に指す ID（`vm-42` のような値）を **moid** と呼ぶ。コードの場所は、バックエンドを `src/vcenter_event_assistant/` から、プラグイン API を `packages/plugin-api/src/vcenter_event_assistant_plugin_api/` から書く。行番号は、本書を書いた時点の origin/main（dc6f5cf）のものである。

## 進捗

| PR | 内容 | 状態 |
|---|---|---|
| A | 本書 | マージ済み [PR #368](https://github.com/t-m0riyama/vcenter-event-assistant/pull/368) |
| B | 完了したタスクの組み込みコレクタ（収集、正規化、間隔の既定、モック、テスト、文書） | マージ済み [PR #370](https://github.com/t-m0riyama/vcenter-event-assistant/pull/370) |

各 PR は単独でマージでき、テストが通る状態にする。

## Context

障害の調査では、「その時刻に誰が何の操作をして、成功したのか、何秒かかったのか」を知りたい。今は組み込みのイベントコレクタ（`builtin.vcenter.events`）が `TaskEvent` を取り込んでいるが、これはタスクの**開始**を表すだけで、失敗したかどうかも所要時間も分からない。

そこで、vCenter の TaskHistoryCollector から完了したタスクを取り、1 タスクを 1 件のイベントとして保存する。イベントタブ・タイムライン・要注目スコア・アラート・ダイジェストは、イベントとしてそのまま扱える。

決めたこと（利用者の決定）:
- 取り込むのは、成功・失敗・キャンセルのすべてとする。
- 種別（`event_type`）に結果を含める。`task.success.<操作>`・`task.error.<操作>`・`task.canceled.<操作>` の形にする。スコアルール・種別ガイド・障害パターンは種別の完全一致で引くので、失敗だけにルールやガイドを付けられる。
- 開始時刻・所要時間・エラーの内容はメッセージに書く。プラグイン API・DB・API・画面は変えない。
- PR B の実装は Codex に任せ、差分はサブエージェントでレビューする。

## 1. 前提（コードで確かめたこと）

### 組み込みコレクタとカーソル

- 組み込みのコレクタは、プラグイン API の `EventCollector` を継承して本体の中で動く（`plugins/builtin.py:49-90` の `EventsCollector`）。実装するのは、`si`（ServiceInstance）と `since` を受け取ってイベントを返す `fetch` と、モック用の `fetch_mock` だけである。接続の開閉とスレッドへの退避は基底が行う。
- カーソルは基底が管理する（`collector.py:279-290`）。返したイベントの `occurred_at` の最大値を次のカーソルにし、次回は 1 秒戻した時刻を `since` として渡す（`cursors.py`）。空のバッチでは前回のカーソルを保つ（`cursors.py:75-79`）ので、同じ範囲を読み直し続けることはない。`since` が `None`（初回）のときの範囲は取得側が決める。イベントでは 1 日前からである（`collectors/events.py:72-75`）。
- 重複は `(vcenter_id, collector_id, vmware_key)` で捨てる（`services/ingestion.py:116-118`、`db/models.py:157`）。新しい `collector_id` を使えば、イベントの `key` と衝突しない。`vmware_key` と `chain_id` の列は int32 である（`db/models.py:174-175`）。範囲外の値は PostgreSQL が INSERT を拒否するので、取得側でスキップする（`examples/example-event-collector` と同じ扱い）。
- 対象は、プラグイン API の `vmware.event_entities` で取れる（`vmware.py:324-383`）。データオブジェクトの属性を順に見て、管理対象の参照を対象として拾う。名前は `<属性名>Name`（`entity` なら `entityName`）から取るので、vCenter への問い合わせは起きない。

### 間隔と有効・無効

- 組み込みのコレクタは既定で有効である（`plugins/registry.py:299`）。更新した時点で収集が始まる。
- 間隔は、環境変数 → 画面（DB）→ TOML → 既定、の順に決まる。既定は `_legacy_interval`（`plugins/registry.py:346-353`）が返し、`builtin.vcenter.events` には `EVENT_POLL_INTERVAL_SECONDS`（120 秒）を、それ以外の `builtin.vcenter.*` にはすべて `PERF_SAMPLE_INTERVAL_SECONDS`（300 秒）を返す。このままでは、新しい組み込みのコレクタの manifest の `default_interval_seconds` が効かない。

### スコアと見え方

- 要注目スコア（`rules/notable.py`）は、severity が error なら +40、warning なら +20、メッセージのどこかに fail・error・lost・timeout・corrupt があれば +10 で、上限は 100 である。
- タイムラインは、既定で `min_score=1` 以上の行だけを一覧に出す（`services/incident_timeline_view.py:1011` 付近）。「新しい種別」のハイライトも、絞った後の行から集計する（`services/incident_timeline_view.py:698-719`）。
- ダイジェストの要注目の件数は 40 点以上を数え、要注目のまとまり（`top_notable_event_groups`）は 1 点以上を対象にする（`services/digest_context.py`）。「件数の多い種別」（`services/metric_ranking.py:107-113`）はスコアで絞らない。
- 障害パターン（`services/event_patterns/definitions.py`）は、タスクの種別を使っていない。

### pyVmomi のタスク（pyVmomi 9.0.0.0 の型で確かめた結果）

- `content.taskManager.CreateCollectorForTasks(filter)` が `TaskHistoryCollector` を返す。`ReadNextTasks(maxCount)` で読み、`DestroyCollector()` で破棄する。
- `vim.TaskFilterSpec` は `time`（`vim.TaskFilterSpec.ByTime`）と `state` を持つ。`ByTime.timeType` は必須で、`vim.TaskFilterSpec.TimeOption.completedTime` を指定すると完了時刻で絞れる。
- `vim.TaskInfo` の主な項目:
  - `key`（`task-123` の形の文字列）、`descriptionId`（`VirtualMachine.powerOn` など。必須）、`name`
  - `state`（`success`・`error`・`queued`・`running`）、`cancelled`、`error`、`reason`、`eventChainId`
  - `entity`・`entityName`、`locked`、`result`、`queueTime`・`startTime`・`completeTime`
- 次の 4 点は取り違えやすい。
  - `error` には、`LocalizedMethodFault` がほどかれて **fault 本体** が入る。文は `error.msg` にある。`localizedMessage` という属性は無い。
  - キャンセルの fault は **`vmodl.fault.RequestCanceled`** である（`vim.fault.RequestCanceled` は存在しない）。
  - `cancelled` は「キャンセルが要求された」印である。要求の後にそのまま成功したタスクでも真になる。
  - `name` は文字列ではない。`ManagedMethod`（名前は `.info.name`）か `UnknownManagedMethod`（名前は `.name`）で、`str()` すると `<... object at 0x...>` になる。
- `completeTime` は、型の上では省略できる。
- 操作した利用者は、`reason` が `vim.TaskReasonUser` のときの `userName` にある。ほかの理由は `TaskReasonSchedule`・`TaskReasonAlarm`・`TaskReasonSystem` である。
- `eventChainId` は、そのタスクの `TaskEvent` の `chainId` と同じ値になる。

## 2. 収集

- 新しいファイル `collectors/tasks.py` に、`fetch_tasks_from_connection_blocking(si, *, since, max_pages=100)` と `normalize_task(info)` を置く。形は `collectors/events.py` の `fetch_events_from_connection_blocking` と `normalize_event` に倣う。
- 絞り込みは次のとおりにする。

  ```python
  spec = vim.TaskFilterSpec(
      time=vim.TaskFilterSpec.ByTime(
          timeType=vim.TaskFilterSpec.TimeOption.completedTime,
          beginTime=since or (now - timedelta(days=1)),
          endTime=now,
      ),
      state=[vim.TaskInfo.State.success, vim.TaskInfo.State.error],
  )
  ```

- `ReadNextTasks(500)` を最大 `max_pages` 回読む。上限に達したら warning を出す。`finally` で必ず `DestroyCollector()` する。
- **`occurred_at` は完了時刻（`completeTime`）にする。** カーソルは `occurred_at` の最大値で進むので、絞り込みの `completedTime` とそろえる。開始時刻にすると、長くかかったタスクがカーソルより前の時刻で現れ、取りこぼす。開始時刻はメッセージに書く。
- 新しい組み込みのコレクタ `TasksCollector(EventCollector)` を `plugins/builtin.py` に足す。

  | 項目 | 値 |
  |---|---|
  | `id` | `builtin.vcenter.tasks` |
  | `display_name` | `vCenter Tasks` |
  | `default_interval_seconds` | 120 |
  | `description` | 日本語で、完了したタスクの結果と所要時間を取り込むこと、成功も入ること、無効にできることを書く |

  `fetch` は `_event()`（`plugins/builtin.py:33-46`）で `EventInput` にして返す。`builtin_collectors()` に加える。
- `_legacy_interval` は、`builtin.vcenter.tasks` にも `EVENT_POLL_INTERVAL_SECONDS` を返すように直す。`PERF_SAMPLE_INTERVAL_SECONDS` を返すのは、既存のメトリクスのコレクタ 3 つ（`host_quickstats`・`host_performance`・`datastore_capacity`）の ID だけに限る。こうすると、今後の組み込みのコレクタでは manifest の既定が効く。

## 3. 保存する形

1 つの完了したタスクを 1 件のイベントにする。

| 項目 | 値 |
|---|---|
| スキップ | 次のどれかに当たるタスクは、warning を出して捨てる。`key` から `task-NNN` の数字が読めない。数字が int32 を超える。`completeTime` が無い（現在時刻で補うとカーソルが先へ飛ぶので、補わない） |
| `vmware_key` | `task-NNN` の数字 |
| `occurred_at` | `completeTime`（タイムゾーン付きにそろえる） |
| `event_type` | `task.<結果>.<操作>` |
| `severity` | 成功は `info`、失敗は `error`、キャンセルは `warning` |
| `message` | 下の「メッセージ」 |
| `user_name` | `reason` が `TaskReasonUser` のときの `userName`。ほかの理由では空にする |
| 対象 | `event_entities(info)` の結果をそのまま使う |
| `chain_id` | `eventChainId`。int32 を超えたら空にする |

### 結果と操作

結果は次の順で決める。`cancelled` は要求の印なので、成功の判定を先にする。

1. `state` が `success` なら `success`
2. `state` が `error` で、`error` が `vmodl.fault.RequestCanceled` か、`cancelled` が真なら `canceled`
3. それ以外の `error` は `error`

操作は `descriptionId` を使う。空なら `name` から取る（`ManagedMethod` なら `.info.name`、`UnknownManagedMethod` なら `.name`）。それも取れなければ `unknown` にする。種別の長さは 512 文字以内に収まる（`limits.MAX_EVENT_TYPE`）。超えたら `unknown` にする。

### メッセージ

英語で書く。vCenter のイベントのメッセージにそろえるためと、失敗の行にスコアのキーワード（`failed`）を効かせるためである。

```text
Task VirtualMachine.powerOn succeeded (started: 2026-11-24T01:02:03+00:00, duration: 12.3s, reason: user)
Task VirtualMachine.powerOn failed: <エラーの文> [<fault の型名>] (started: ..., duration: ..., reason: user)
Task VirtualMachine.migrate was canceled (started: ..., duration: ..., reason: user)
```

- エラーの文は、`error.msg`、無ければ `error.faultMessage` の文、それも無ければ fault の型名の順に取る。
- エラーの文が取れず fault の型名を使うときは、型名が二重にならないよう `failed: <型名>` とし、`[<型名>]` は付けない。
- `startTime` が無い（待ち行列のまま終わった）ときは、`started` と `duration` を省く。
- `reason` は `user`・`schedule`・`alarm`・`system` のどれかを書く。スケジュールやアラームの名前があれば添える。
- **対象の名前はメッセージに入れない。** 対象の名前に fail などの語が含まれると、成功の行にも 10 点が付いてタイムラインに出てしまうからである。対象は対象の列で見える。

### 対象

`event_entities(info)` は、`entity`（名前は `entityName`）を主な対象として返す。ほかに、タスクがロックした対象（`locked`、ホスト・VM・データストアなど）と、タスクの結果の管理対象（`result`、クローンした VM など）も子の対象として返す。どちらも調査に役立つので残す。タイムラインの moid の絞り込みは主な対象の列だけを見る（`services/incident_timeline_view.py:949` 付近）ので、子の対象で行が増えることはない。この形はテストで固定する。

### スコアと見え方

- 失敗は 50 点（error +40、`failed` +10）、キャンセルは 20 点、成功は 0 点になる。ただし、エラーの文やスケジュールの名前にキーワードが含まれると +10 される。
- 成功の行はタイムラインの一覧には出ない。概要の件数のバーには数えられる。
- 失敗は、ダイジェストの要注目（40 点以上）と Web の事前調査に入る。キャンセルは、ダイジェストの要注目のまとまり（1 点以上）に入る。
- タイムラインの「新しい種別」には、導入の直後に `task.error.*` と `task.canceled.*` が出る。0 点の `task.success.*` は既定では出ない。
- 保持期間は、ほかのイベントと同じ 7 日（`EVENT_RETENTION_DAYS`）である。

## 4. PR の分け方

### PR A: 本書

- 本書を足す。

### PR B: 完了したタスクの組み込みコレクタ

- `collectors/tasks.py`（新規）: 2 章の収集と、3 章の正規化。
- `plugins/builtin.py`: `TasksCollector` と、`builtin_collectors()` への追加。
- `plugins/registry.py`: `_legacy_interval` の修正。
- `mocks/mock_collectors.py`: `fetch_mock_tasks_blocking(since)` を足し、`TasksCollector.fetch_mock` から返す。成功・失敗・キャンセルを 1 件ずつ返す。キーと時刻は、ホストの切断のモック（`mocks/mock_collectors.py:70-84`）と同じく 30 分の枠で決める。現在時刻から作ると、収集のたびに失敗の行が増え、モックモードのアラートとダイジェストが埋まる。
- テスト:
  - `tests/test_tasks_collector.py`（新規）: 本物の `vim.TaskInfo` を組み立てて `normalize_task` を確かめる。`vim.TaskInfo` は `queueTime`・`reason`・`task`・`cancelable`・`eventChainId` が無いと作れない。
    - 3 つの結果。`cancelled=True` で `state=success` なら成功になること。`vmodl.fault.RequestCanceled` ならキャンセルになること。
    - `descriptionId` が空文字のとき、`ManagedMethod`・`UnknownManagedMethod` から操作を取ること。
    - スキップ（`key` が読めない、int32 を超える、`completeTime` が無い）。`startTime` が無いときのメッセージ。
    - `reason` の 4 種と `user_name`。エラーの文の取り方。
    - 対象（主な対象が `entity`、`locked` と `result` が子）と `chain_id`。
  - 取得: `taskManager` を MagicMock で差し替え、絞り込みの中身、ページの読み方、`max_pages` の warning、例外のときも `DestroyCollector` を呼ぶことを確かめる（`tests/test_events_collector.py:204-216` の書き方）。
  - カーソルが完了時刻で進むこと（`tests/test_builtin_collectors_with_fakes.py` の書き方）。プラグイン API の `FakeServiceInstance.RetrieveContent()` は呼ぶたびに新しい content を返すので、`RetrieveContent` ごと差し替える。プラグイン API は変えない。
  - `tests/test_collector_plugins.py:48` の、組み込みのコレクタの集合の完全一致を 5 つに直し、テスト名（`test_registry_contains_four_builtin_collectors`）も直す。`_legacy_interval` のテストを足す。
  - モックモードのテスト（`tests/test_mock_mode.py`）が、イベントの件数に頼っていないか確かめる。
- 文書:
  - `docs/userguide/plugins.md`: 組み込みのコレクタの表（51-54 行）と、「次の 4 つ」（46 行）、「組み込みの 4 つ」（110 行）。
  - `docs/operations/collector-plugins.md`、`docs/userguide/events.md`（タスクの行の種別の名前と見え方）、`docs/features/features_list.md`。
  - `EVENT_POLL_INTERVAL_SECONDS` がタスクの収集の間隔にも効くこと: `docs/operations/backend-operations.md` の設定の一覧、`docs/development/backend.md:177` 付近、`.env.example`（今は項目が無いので足す）。
  - `CHANGELOG.md`。6 章の「更新した時点で変わること」も書く。
  - 10 案の 3a の行に、本書へのリンクを足す。

## 5. 確認方法

- PR B のテストに加えて、全体の `uv run pytest`、ruff、型検査を CI と同じコマンドで流す。Codex のサンドボックスでは SSH の統合テストが落ちるので、Claude 側で流し直す。
- `MOCK_MODE=true` で起動し、次を確かめる。
  - イベントタブに `task.*` の行が出る。
  - タイムラインには失敗とキャンセルだけが出る。
  - 時間がたっても、失敗の行が増え続けない。
- 実機か vcsim があれば、次を確かめる。
  - VM の電源操作の成功と失敗で、行が 1 件ずつ入る。同じ範囲を読み直しても増えない。
  - `TaskFilterSpec` で `entity` を省いても、すべての対象のタスクが返る。
  - `ReadNextTasks` が完了時刻の古い順に返す。

## 6. リスク

- **`TaskFilterSpec` の既定の範囲:** `entity` を指定しなければすべての対象のタスクが返る、という前提で作る。実機で確かめ、違っていればルートフォルダを `recursion=all` で指定する。
- **`max_pages` で打ち切ったときの取りこぼし:** カーソルは、読んだ分の完了時刻の最大値に進む。`ReadNextTasks` が完了時刻の古い順に返さないと、読まなかったタスクのうち、それより前に完了したものは二度と読まれない。上限は 1 回 5 万件なので、普通は届かない。実機で並びを確かめ、古い順でなければ、打ち切ったときに `endTime` を縮めて読み直す。
- **更新した時点で変わること:** 組み込みのコレクタは既定で有効なので、更新すると収集が始まる。失敗したタスクは 50 点になるので、閾値が 50 以下のイベントスコアのアラートルールが新たに発火しうる。ダイジェストの要注目と Web の事前調査にも入る。CHANGELOG に書く。
- **二重に数える:** 失敗した vMotion は、`vim.event.VmFailedMigrateEvent` と `task.error.*` の 2 行になる。スコア・アラート・ダイジェストでは 2 件と数えられる。
- **件数:** バックアップ製品のスナップショットの作成などで成功のタスクが多い環境では、行が増える。「件数の多い種別」はスコアで絞らないので、`task.success.*` が入りうる。ただし、種別は操作ごとに分かれ、開始の `TaskEvent` がすでに同じ件数入っているので、上位の顔ぶれはあまり変わらない。重すぎれば、このコレクタを無効にできる。
- **開始と完了の 2 行:** `TaskEvent`（開始）と完了したタスクは別の行になる。`chain_id` で結べるが、API と画面で結んで見せるのは範囲外とする。

## 7. 範囲外（後続）

- 実行中のタスク。状態が変わるので、取り込んだ行を更新する仕組みが要る（10 案の 3b で扱う）。
- 所要時間の専用の列と、所要時間での並べ替えや絞り込み。
- タスクの種別のガイドの雛形。
- 障害パターンへの組み込み（`vmotion-failures` に `task.error.VirtualMachine.migrate` などを足す）。
- `TaskEvent` と完了したタスクを `chain_id` で結んで見せること。
- 「件数の多い種別」から `task.success.*` を除くこと（件数が問題になったら）。
