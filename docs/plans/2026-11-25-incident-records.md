# インシデント記録

最終更新: 2026-11-25（計画）

[障害調査を楽にする機能 10 案](2026-11-22-troubleshooting-ideas.md)（以下「10 案」）の「案 7」にあたる。障害ごとに「インシデント」を作り、状態・担当・経過のメモと、関係するイベント・通知・スナップショットをまとめて残す。Issue は起票していない。

コードの場所は、バックエンドを `src/vcenter_event_assistant/` から、画面を `frontend/src/` から書く。行番号は、本書を書いた時点の origin/main（7950802）のものである。

## 進捗

| PR | 内容 | 状態 |
|---|---|---|
| A | 本書 | マージ済み [PR #382](https://github.com/t-m0riyama/vcenter-event-assistant/pull/382) |
| B | 表・移行・API・保持期間の削除 | マージ済み [PR #383](https://github.com/t-m0riyama/vcenter-event-assistant/pull/383) |
| C | 画面（インシデントのタブと、各画面からの追加）と文書 | レビュー中 |

各 PR は単独でマージでき、テストが通る状態にする。

## Context

障害の調査では、何が起きたか、誰が何をしたか、どこまで分かったかを、調査の途中から書き残しておきたい。今のアプリでこれに使えるのは、スナップショットの運用メモと、イベントのコメントだけである。

- イベントのコメント（`EventRecord.user_comment`）は、イベントと一緒に 7 日で消える。
- スナップショットは 1 件ずつ独立していて、複数のスナップショットを 1 つの障害としてまとめられない。状態（対応中か解決済みか）や担当も持てない。
- スナップショットは作成から 90 日で消える。障害の記録として残したいものも、同じ期間で消える。

決めたこと（利用者の決定、2026-11-25）:
- **画面:** 新しい「インシデント」タブを足し、一覧と詳細を置く。タイムライン・通知履歴・イベントの一覧から「インシデントに追加」で紐付ける。
- **イベントの残し方:** 紐付けたときに、時刻・種別・対象・本文・スコアなどの要点をインシデント側に写す。元の行が 7 日で消えても読める。
- **スナップショット:** インシデントに紐付いたスナップショットは、インシデントが残っているあいだ、保持期間の削除から外す。インシデントは、解決してから 90 日で消える。
- **作り方:** 手動だけ（operator 以上）。通知履歴から「インシデントを作る」はできるが、アラートの発火で自動では作らない。

本書で決めたことは次のとおり。利用者にはまだ確かめていないので、計画の PR で確認してもらう。
- **通知履歴も写す:** 通知履歴も、ルールを消すと一緒に消え（`ondelete="CASCADE"`）、90 日で消える。イベントと同じ理由で、紐付けたときに要点を写す。
- **結果の無いスナップショットは紐付けない:** 結果を持たないスナップショットは、7 日を過ぎると中身を表示できないので、紐付けを断る（4 章）。
- **削除は admin だけ:** インシデントと経過の行の削除は admin だけができる。紐付けを外すこと（写しも消える）は operator もできる。紐付けは調査の途中で付け外しするものであり、経過は記録として残すものだからである。

10 案の 5 章の注意を引き継ぐ。インシデント記録には改ざん耐性がないので、証跡にはならない。誰が何をしたかは、アプリの利用者名を写して残すだけで、署名や改ざんの検知はしない。

## 1. 前提（コードで確かめたこと）

- **スナップショット:** 表 `incident_timeline_manual_snapshots`（`db/models.py:599`、モデル `IncidentTimelineManualSnapshot`、主キーは UUID）。
  - 手動で保存すると、条件（`view_request_payload`）と結果（`result_payload`）を持つ（`api/routes/incident_timeline.py:274`）。ただし、手動でも条件（`view_request`）を送らなかった保存は、結果を持たない（同 284 行、`db/models.py:614` のコメント）。
  - 結果は 1 件 8 MiB まで、行の詳細は 2,000 文字に切り詰める（`MAX_SNAPSHOT_RESULT_BYTES`・`SNAPSHOT_DETAIL_MAX_CHARS`、`api/routes/incident_timeline.py:61・64`）。
  - 自動のスナップショット（`snapshot_kind="auto"`、`services/incident_timeline_snapshot.py`）は、条件とアラートの根拠（`trigger_evidence`）だけを持ち、結果を持たない。
  - 保存した結果が今のスキーマで読めないときは、読むと None になる（同 142-151 行）。一覧は結果を読まずに、`result_payload IS NOT NULL` で「結果あり」を決める（同 352-353 行）。
  - 保存できるのは operator 以上、一覧と詳細は viewer でも読める。削除の API は無い。
- **保持期間の削除:** `jobs/scheduler.py:119` の `purge_retention` が、1 つのトランザクションで次の順に削除する（同 122-150 行）。ログ、ログの型、インベントリ、イベント、メトリクス、通知履歴、ダイジェスト、スナップショットの行、スナップショットの結果、ログインのセッション。
  - スナップショットは `created_at` が `INCIDENT_TIMELINE_SNAPSHOT_RETENTION_DAYS`（既定 90、`settings.py:99`）を過ぎた行を消す（`services/ingestion.py:313`）。
  - 結果だけを先に消す設定もある。`INCIDENT_TIMELINE_SNAPSHOT_RESULT_RETENTION_DAYS`（既定 0 で無効、`settings.py:107`）を過ぎた行の `result_payload` を NULL にする（`services/ingestion.py:327`）。
  - SQLite でも外部キーと CASCADE が効く（`db/session.py:22-36` の `PRAGMA foreign_keys=ON`）。SQLite の待ち時間（busy timeout）は 30 秒（同 33 行）。
- **イベント:** 表 `events`（`db/models.py:155`）。主キーは整数の連番で、自然キーは `(vcenter_id, collector_id, vmware_key)`（一意制約 `uq_event_collector_vmware_key`）。
  - 本文（`message`）は長さの上限の無い Text。利用者名（`user_name`）と、operator 以上が付けるコメント（`user_comment`、8,000 文字まで、`api/schemas/events.py:51`）を持つ。
  - vCenter を消すと、イベントも一緒に消える（`ondelete="CASCADE"`、`api/routes/vcenters.py:129-138`）。
  - SQLite の連番は `AUTOINCREMENT` ではないので、最大の id の行が消えると、同じ id が再び使われることがある（[案 8 の計画書](2026-11-24-log-patterns.md) の 8 章と同じ事情）。
- **通知履歴:** 表 `alert_history`（`db/models.py:536`）。ルールを消すと一緒に消える。`ALERT_HISTORY_RETENTION_DAYS`（既定 90）で消える。admin は 1 件ずつ消せる（`api/routes/alerts.py:350`）。
  - API の読み取り（`AlertHistoryRead`、`api/schemas/alerts.py:102-118`）は、ルール名・種別・レベル・状態・`context_key`・発生時刻（`occurred_at`）と、`context_key` から解決した vCenter の ID・moid・対象名を返す。vCenter の名前は返さない。
  - 対象を解決するのは、ルールの種別が `metric_threshold` と `event_pattern` のときだけである（`api/routes/alerts.py:239-264` の `_history_item_to_read`）。`event_score` は vCenter も対象も NULL になる。
  - 解決には、メトリクスと、最新の `event_entities` を使う（同 215 行の `_resolve_history_entities`、設定の `perf_sample_interval_seconds` が要る）。どちらも 7 日で消えるので、古い通知では対象名が NULL になる。2 つの関数はルーターの中の非公開の関数である。
- **タイムラインの行:** `IncidentTimelineViewItem`（`api/schemas/incident_timeline_view.py:161`）。種類（`kind`）は `event`・`alert`・`metric`・`log`。
  - 元の行への参照（`ref`、同 131 行）は、イベントなら `event_id`、通知なら `alert_history_id` を持つ。
  - 同じ種類の出来事を 1 行にまとめた行（`count` が 2 以上）も、`ref.event_id` は先頭の 1 件だけを持つ。まとめた全件の ID は、行には無い。
  - 構成変更と障害パターンのカードは `event_ids` を持つが、最大 20 件で切っている（`services/incident_timeline_view.py:116・1000・1143`）。
  - 保存したスナップショットの結果を表示しているとき、行の ID が指す元の行は、もう消えていることがある。
- **楽観ロック:** アラートルールの更新は、更新前に読まずに、`revision`（UUID）を WHERE に入れて更新する（`api/routes/alerts.py:135` のコメント「更新前に読み取ると、SQLite の同時更新で書き込み待ちと競合する」）。合わなければ 409 を返し、`X-VEA-Error-Code: alert_rule_stale` で区別する（同 151-162 行）。利用者が切り替わったときも 409 になる（`api/auth_deps.py:82-86`）ので、画面はこの見出しで区別する。
- **利用者:** 要求ごとの利用者は `Principal`（`api/auth_deps.py:42`）で、`username`・`display_name`・`user_id`・`role` を持つ。認証を無効にしているときは、利用者名が `anonymous`、ロールが admin になる（同 68 行）。
- **部分一致:** `services/sql_like.py` の `contains_case_insensitive` は、`%` と `_` を逃がして `ilike` で比べる。SQLite と PostgreSQL で同じ結果になる。
- **PostgreSQL の CI:** `.github/workflows/ci.yml:210-228` は、決まったファイルを `-k "postgres and (...)"` で絞って流す（手順 1 は 216-217 行、手順 2 は 223-226 行）。新しいテストは、ファイルを一覧に足し、`-k` にも語を足さないと流れない。PostgreSQL のテストは `VEA_TEST_POSTGRES_URL` で専用の DB を受け取る（例: `tests/test_log_pattern_ledger.py:38`）。
- **タブ:** 主なタブは 9 つ（`App.tsx:179` の `mainTabs`、概要・イベント・ログ・グラフ・ダイジェスト・通知履歴・チャット・タイムライン・設定）。ハッシュでタブを開く（`routing/appHashRouting.ts`）。タブの列は折り返しも横のスクロールも無い flex で（`App.css:154-165`）、中身の幅は最大 1,200 px である。
- **別のタブを開く仕組み:** タイムラインから「グラフで開く」は、ハッシュを使わず、アプリの状態（`App.tsx:82-85` の `metricsReplaySource` と `nonce`）で開く相手を渡す。
- **タイムラインのハッシュ:** 条件だけを扱う（`routing/timelineHash.ts:111-195`）。表示中は条件でハッシュを書き戻す。ある時刻の前後 30 分を開くハッシュを作る関数 `timelineEntryHash`（同 224 行）がある。

## 2. データの形

### 表

新しい表は 5 つ。整数の主キーを持つ表は `sqlite_autoincrement=True` にする。紐付けを外した直後に同じ id が別の行に使われ、古い画面から別の紐付けを外すことを防ぐためである。

**`incidents`**（インシデント）

| 列 | 型 | 内容 |
|---|---|---|
| `id` | UUID | 主キー |
| `title` | String(200) | 件名。必須で、空白だけは不可 |
| `status` | String(16) | `open`（対応中）・`monitoring`（様子見）・`resolved`（解決） |
| `level` | String(16) NULL | `critical`・`error`・`warning`。アラートのレベルと同じ語。任意 |
| `assignee` | String(256) NULL | 担当。自由な文字列（下記） |
| `summary` | Text | 原因と対応の要約。20,000 文字まで。空でよい |
| `started_at` | DateTime NULL | 障害が始まった時刻。任意 |
| `resolved_at` | DateTime NULL | 解決にした時刻。サーバが入れる |
| `created_by` / `updated_by` | String(256) | 作った人・最後に変更した人の名前（下記） |
| `created_at` / `updated_at` | DateTime | `updated_at` は、紐付けとメモを含め、最後に何かを変えた時刻 |
| `revision` | UUID | 楽観ロック。PATCH で項目を変えたときだけ変える |

CHECK 制約を 2 つ付ける。`status` が 3 つの語のどれかであること。`status = 'resolved'` と `resolved_at IS NOT NULL` が一致すること。索引は `(status, updated_at)` と `resolved_at`。

担当は、利用者の表への外部キーにしない。認証を無効にしていると利用者の表が空であり、外部のディレクトリの利用者は一度ログインするまで表に無いためである。

人の名前は、`Principal` から、その時点の文字列で写す。`display_name` があって `username` と違えば「表示名（ユーザー名）」、無ければ `username` にする。同じ表示名の人を区別するためである。利用者を消したり名前を変えたりしても、記録は変わらない。認証を無効にしているときは `anonymous` になる。

**`incident_entries`**（経過のメモと自動の記録）

| 列 | 型 | 内容 |
|---|---|---|
| `id` | Integer | 主キー |
| `incident_id` | UUID | FK → `incidents.id`、`ON DELETE CASCADE`。索引 |
| `kind` | String(16) | `note`（メモ）・`change`（項目の変更）・`link`（紐付けと解除） |
| `body` | Text | メモの本文（4,000 文字まで）。自動の記録では、変更の内容を短い日本語で入れる |
| `author` | String(256) | 書いた人。自動の記録では、操作した人 |
| `created_at` | DateTime | |
| `deleted_by` / `deleted_at` | String(256) NULL / DateTime NULL | 削除した人と時刻 |

経過の行は追記だけで、編集はしない。admin は、誤って書いた秘密などを消すために、メモも自動の記録も削除できる。削除すると、本文を空にし、`deleted_by` と `deleted_at` を入れる。行と `author` は残す。件名や担当を変えたときの自動の記録は、変更前の値を本文に含む。件名に貼った秘密を消すときは、その記録も削除する。

**`incident_events`**（紐付けたイベントの写し）

| 列 | 内容 |
|---|---|
| `id`、`incident_id`（FK、CASCADE、索引） | |
| `event_id` | 元の行の id。外部キーにしない（イベントは 7 日で消える） |
| `vcenter_id`、`collector_id`、`vmware_key` | 元の行の自然キー。外部キーにしない |
| `vcenter_name` | 写した時点の vCenter の名前 |
| `occurred_at`、`event_type`、`severity`、`notable_score` | 写し |
| `entity_type`、`entity_name`、`entity_moid` | 主な対象の写し。関連する対象（`event_entities`）は写さない |
| `user_name` | 写し（イベントを起こした利用者。個人に関する情報。7 章） |
| `message` | 写し。2,000 文字に切り詰める（スナップショットと同じ上限） |
| `user_comment` | 写した時点のコメント。2,000 文字に切り詰める。後でイベントのコメントを直しても、写しは変わらない |
| `added_by`、`added_at` | 紐付けた人と時刻 |

一意制約は `(incident_id, vcenter_id, collector_id, vmware_key)`。id ではなく自然キーで重複を判定するのは、SQLite で id が再び使われることがあるためである。

**`incident_alerts`**（紐付けた通知の写し）

| 列 | 内容 |
|---|---|
| `id`、`incident_id`（FK、CASCADE、索引） | |
| `alert_history_id`、`rule_id` | 元の行の id。外部キーにしない |
| `rule_name`、`rule_type`、`alert_level`、`state`、`context_key`、`occurred_at` | 写し |
| `vcenter_id`、`vcenter_name`、`entity_moid`、`entity_name` | 紐付けた時点で解決できた値。解決できなければ NULL（下記） |
| `added_by`、`added_at` | |

一意制約は `(incident_id, alert_history_id, occurred_at)`。id の再利用で別の通知を同じものと見なさないよう、発生時刻も含める。

通知の対象の解決は、`api/routes/alerts.py` の `_resolve_history_entities` と `_history_item_to_read` にあった対象解決の処理を、サービス（`services/alert_history_read.py`）に切り出して共用する。紐付けでは要求ごとにまとめて解決する。通知履歴の API の応答形式はルーターで組み立てる。vCenter の名前は、`vcenter_id` から `VCenter.name` を別に引く。`event_score` の通知と、7 日より古い通知では、対象名は NULL になる。

**`incident_snapshots`**（紐付けたスナップショット）

| 列 | 内容 |
|---|---|
| `id`、`incident_id`（FK、CASCADE、索引） | |
| `snapshot_id` | FK → `incident_timeline_manual_snapshots.id`、`ON DELETE CASCADE`。索引 |
| `added_by`、`added_at` | |

一意制約は `(incident_id, snapshot_id)`。スナップショットの中身は写さない。保持期間の削除から外して残す（4 章）。

スナップショットへは外部キーを張る。保持期間の削除と紐付けは、PostgreSQL では表ロック、SQLite では書き込みの直列化で順番に進むため、通常は外部キー違反が起きない。ほかの経路でスナップショットが消えた場合に備え、外部キー違反は「見つからない」として返す（3 章）。

### 上限

インシデントが解決されないまま残ると、写しは消えない。増え方を抑えるため、1 件のインシデントに次の上限を設ける。上限は設定にせず、コードの定数にする。

| もの | 上限 |
|---|---|
| 件名 | 200 文字 |
| 要約 | 20,000 文字 |
| メモ 1 件 | 4,000 文字 |
| 紐付けるイベント | 500 件 |
| 紐付ける通知 | 200 件 |
| 紐付けるスナップショット | 10 件 |
| 経過のメモ（削除した行を含む。自動の記録は数えない） | 1,000 件 |
| 1 回の紐付けの要求で送れる ID | 100 件 |

インシデント 1 件が最大でどれだけの大きさになるかを、日本語を UTF-8 で 1 文字 3 バイトとして見積もると、次のとおり。

| もの | 最大 |
|---|---|
| イベントの写し | 1 件約 20 KB（本文とコメント 4,000 文字と、種別・利用者名・対象などの列を上限まで）× 500 件 = 約 10 MB |
| 通知の写し | 1 件約 2 KB × 200 件 = 約 0.4 MB |
| 経過のメモ | 1 件約 12 KB × 1,000 件 = 約 12 MB |
| 経過の自動の記録 | 1 行約 2 KB。件数は操作の回数で決まり、上限は無い |
| 要約 | 約 60 KB |
| 合計（スナップショットと自動の記録を除く） | 約 23 MB |
| 紐付けたスナップショット | 1 件 8 MiB × 10 件 = 最大 80 MiB |

実際の大きさは、これよりずっと小さい。インシデントの件数には上限を設けないので、全体の大きさはインシデントの数に比例する。運用の文書に、この最大の値と、解決したインシデントだけが消えることを書く。

## 3. API（PR B）

ルーターは `api/routes/incidents.py`、接頭辞は `/api/incidents`。パスの `{id}` は文字列で受け取り、UUID として読めなければ 404 を返す（スナップショットの API と同じ、`api/routes/incident_timeline.py:383-389`）。どの経路にも `Require*` を付け、`tests/test_route_policy.py` の一覧に足す。

| メソッドとパス | ロール | 内容 |
|---|---|---|
| `GET /api/incidents` | viewer | 一覧 |
| `GET /api/incidents/{id}` | viewer | 詳細 |
| `POST /api/incidents` | operator | 作る。最初に紐付けるものも送れる |
| `PATCH /api/incidents/{id}` | operator | 件名・状態・重大度・担当・要約・開始の時刻を変える |
| `DELETE /api/incidents/{id}` | admin | 消す。経過と紐付けも消える |
| `POST /api/incidents/{id}/entries` | operator | メモを足す |
| `DELETE /api/incidents/{id}/entries/{entry_id}` | admin | 経過の行を消す（本文を空にする） |
| `POST /api/incidents/{id}/events` | operator | イベントを紐付ける |
| `POST /api/incidents/{id}/alerts` | operator | 通知を紐付ける |
| `POST /api/incidents/{id}/snapshots` | operator | スナップショットを紐付ける |
| `DELETE /api/incidents/{id}/{events,alerts,snapshots}/{link_id}` | operator | 紐付けを外す |

### 要求と応答

本文に未知の項目が含まれる場合、またはメモの本文が空白だけの場合は 422 を返す。

スキーマは `api/schemas/incidents.py` に置く。時刻は UTC の ISO 8601 で返す。

- **一覧 `GET`:** 引数は `status`（複数指定でき、既定は `open` と `monitoring`）、`q`（件名の部分一致、`contains_case_insensitive`）、`limit`（既定 50、最大 200）、`offset`。`updated_at` の新しい順。
  - 応答は `{"items": [...], "total": n}`。各項目は、インシデントの列（`summary` を除く）と、`event_count`・`alert_count`・`snapshot_count`。件数は、表ごとに `GROUP BY incident_id` の問い合わせを 1 本ずつ流して数える（一覧の件数ぶん問い合わせを流さない）。
- **詳細 `GET`:** 応答は次のものを持つ。
  - インシデントの列すべて（`revision` を含む）。
  - `entries`: 経過の行（古い順）。削除した行は `body` を空にし、`deleted_by`・`deleted_at` を返す。
  - `events`・`alerts`: 写しの行（発生時刻の古い順）と、`source_exists`（元の行がまだあるか）。イベントは自然キー、通知は `(id, rule_id, occurred_at)` で、まとめて引いて判定する。
  - `snapshots`: 紐付けの id と、スナップショットの `snapshot_id`・`operator_note`・`snapshot_kind`・`from_time`・`to_time`・`created_at`・`has_result`。`has_result` は `result_payload IS NOT NULL` で決め、結果の本体は読まない（`defer`）。
- **作成 `POST`:** 本文は `title`（必須）、`status`（既定 `open`）、`level`・`assignee`・`summary`・`started_at`（任意）、`events`・`alerts`・`snapshot_ids`（任意、紐付けの要求と同じ形）。`status` が `resolved` なら、`resolved_at` に今の時刻を入れる。作成と紐付けは 1 つのトランザクションで行う。紐付けの一部が失敗しても、インシデントは作る。
  - 応答は 201 で `{"incident": 詳細, "link_results": {"events": [...], "alerts": [...], "snapshots": [...]}}`。
- **更新 `PATCH`:** 本文は `revision`（必須）と、変える項目だけ。`level`・`assignee`・`started_at` は null を送ると空に戻す。省略した項目は変えない。この区別は `model_fields_set` で行い、`exclude_none` は使わない。`title` は null や空白だけにできない。`summary` の null は空の文字列にする。
  - `resolved_at` は、状態が実際に `resolved` に変わったときに今の時刻を入れ、`resolved` から別の状態に変わったときに NULL に戻す。状態が同じなら変えない。
  - 応答は詳細と同じ形。`revision` が合わなければ 409 で、`X-VEA-Error-Code: incident_stale` を付ける。
- **紐付け `POST .../events`・`.../alerts`:** 本文は `{"items": [{"id": 123, "occurred_at": "..."}]}`。各項目には、時刻の確認として次のどちらかを必ず付ける。どちらも無い項目は 422 にする。
  - `occurred_at`: 元の行の発生時刻と一致するかを確かめる。
  - `occurred_from` と `occurred_to`: 元の行の発生時刻が、この範囲（両端を含む）に入るかを確かめる。カードのように、個々の時刻を持たず、期間だけを持つものに使う。

  確認に通らなければ `not_found` にする。古い画面や保存したスナップショットの結果が送った id が、再び使われた別の行を指したときに、関係の無い行の写しを作らないためである。
  - 比べるときは、サーバが両方を UTC の tz 付きの値にそろえてから、マイクロ秒まで比べる。SQLite は tz の無い値を返すので、そのまま比べると例外になる。
  - 通知の発生時刻はマイクロ秒を持つ（`db/models.py:555-561`）。画面は、API から受け取った時刻の文字列を、`Date` を通さずにそのまま送る。`Date` を通すとミリ秒に切れて一致しない。イベントの一覧、通知履歴、タイムラインの行は `occurred_at` を送る。カードの `event_ids` は個々の時刻を持たないので、カードの `first_utc` と `last_utc` を範囲として送る。
- **紐付け `POST .../snapshots`:** 本文は `{"snapshot_ids": ["uuid", ...]}`。UUID として読めない値は 422。
- **紐付けの共通の規則:**
  - 1 回に 101 件以上を送ると 422。
  - 同じ ID が 2 回以上あれば、最初の 1 回だけを扱う。
  - 送られた順に処理する。元の行と紐付けの有無を確認した上で、未紐付けの ID に対しては紐付け数が上限に達していれば `limit_exceeded` にする。紐付け済みの ID は上限に達していても `already_linked` を返す。
  - 応答は `{"results": [{"id": ..., "result": "...", "link_id": ...}], "added": n}`。`link_id` は `added` と `already_linked` のときだけ入る。
- **紐付けを外す `DELETE`:** `link_id` が、パスのインシデントの紐付けでなければ 404。
- **メモの上限:** メモが 1,000 件に達したインシデントへのメモの追加は、409 と `X-VEA-Error-Code: incident_entry_limit` で断る。画面は「メモが上限に達しました。新しいインシデントを作ってください」と出す。自動の記録は上限に数えず、PATCH・紐付け・解除はいつでもできる。上限に達しても、解決にしたり紐付けを外したりできなくならないためである。

### 紐付けは ID ごとに結果を返す

紐付けの要求は、ID ごとに次のどれかを返す。一部が失敗しても、ほかの ID の紐付けは行う。

- `added`: 紐付けた。
- `already_linked`: すでに紐付いていた。
- `not_found`: 元の行が無い、または時刻の確認に通らない。元の行は、保持期間の削除、vCenter やルールの削除、admin の削除で消えることがある。
- `no_result`: 結果を持たないスナップショット（`result_payload IS NULL`）。結果の中身は読まずに判定する。
- `limit_exceeded`: 上限を超えた。

写しは、サーバがデータベースの元の行から作る。画面から送られた写しは受け取らない。

ID ごとの挿入は、それぞれ SAVEPOINT（`session.begin_nested()`）の中で行う。PostgreSQL では、外部キーや一意制約の違反が 1 件起きると、トランザクション全体が使えなくなるためである。一意制約の違反は `already_linked`、スナップショットの外部キーの違反は `not_found` にする。

### 書き込みの順序とロック

インシデントへの書き込みの要求（PATCH、メモの追加と削除、紐付けと解除、インシデントの削除）は、最初の文で値を据え置く UPDATE を流し、インシデントの行をロックする。

```sql
UPDATE incidents SET revision = revision
WHERE id = :id [AND revision = :revision]   -- revision は PATCH のときだけ
RETURNING id
```

行が返らなければ、もう 1 本の問い合わせで 404 と 409 を区別する（アラートルールと同じ）。

この方式は、その UPDATE がトランザクションの最初の書き込みであることが前提である。要求ごとのセッション（`get_session`）は認証と共有で、認証が先に読み取りや `last_seen_at` の更新を流す（`api/auth_deps.py:89-95`、`auth/sessions.py:116・150-151`）。また、テストのインメモリの SQLite では、すべての要求が 1 本の接続を共有する（`db/session.py:87-100`）。そのため、書き込みの経路は、アラートルールの PATCH と同じく専用のセッションを使う（`api/routes/alerts.py:99-110` の `session_scope(isolate_memory=True)` と `Depends(..., scope="function")`）。

最初に書き込むことで、同じインシデントへの書き込みの要求は、トランザクションの終わりまで順番に並ぶ。SQLite では最初の文で書き込みのロックを取るので、読んでから書くときの待ちの競合が起きない（1 章の楽観ロックの注意）。PostgreSQL では行のロックで並ぶ。このロックを取った後で、上限の件数を数え、PATCH の変更前の値を読み、経過の件数を確かめる。こうすると、同時の要求で上限を超えたり、変更前の値を取り違えたりしない。

PostgreSQL では、インシデントの行をロックまたは新規作成してから `incident_snapshots` を `ROW EXCLUSIVE` でロックし、スナップショットの結果の有無を読む。保持期間の処理もインシデントの行を先に処理してから表を `SHARE` でロックする。保持期間の処理は、先頭でトランザクション単位の advisory lock を取得できた 1 本だけが進む。

`updated_at` と `updated_by` は、項目・紐付け・経過が実際に変わったときに更新する。値が同じ PATCH や、1 件も追加できなかった紐付けでは、どちらも据え置く。`revision` は PATCH で項目が変わったときだけ更新するため、紐付けやメモの変更は一覧の並びに反映され、開いている編集画面の保存も続けられる。

### 経過の自動の記録

次の操作をしたとき、サーバが経過に 1 行を足す。本文は「状態を『対応中』から『解決』に変えました」のような短い文にする。

- 状態・件名・重大度・担当・開始の時刻の変更（要約の変更は、長いので内容を記録せず「要約を更新しました」とだけ残す）
- 紐付けと解除（「イベント 3 件を追加しました。1 件は見つかりませんでした」のように、1 回の要求で 1 行）。1 件も追加できなかった要求では書かない

1 回の PATCH で複数の項目を変えたときは、1 行にまとめる。

### チャットには渡さない

インシデントの中身は、チャット（LLM）の文脈に入れない。メモと写しには、利用者名や環境の固有の情報が入るためである。チャットへの組み込みは後続にする（8 章）。

## 4. 保持期間

### インシデント

`INCIDENT_RETENTION_DAYS`（既定 90、0 で削除しない）を足す。解決（`resolved`）にしてからこの日数を過ぎたインシデントを、`resolved_at` で判定して消す。未解決のインシデントは消さない。解決から戻すと `resolved_at` が NULL に戻るので、削除の対象から外れる。

解決した後に紐付けやメモを足しても、保存の期間は延びない。期間は `resolved_at` だけで決まる。

### 紐付いたスナップショットは消さない

スナップショットの 2 つの削除（行の削除と、結果だけの削除）の両方に、「どのインシデントにも紐付いていない」という条件を足す。

```sql
... AND NOT EXISTS (
  SELECT 1 FROM incident_snapshots s
  WHERE s.snapshot_id = incident_timeline_manual_snapshots.id
)
```

結果だけの削除からも外すのは、結果の無いスナップショットは、7 日を過ぎると何も表示できないためである。このため、インシデントに紐付いているあいだは、admin が `INCIDENT_TIMELINE_SNAPSHOT_RESULT_RETENTION_DAYS` で結果を早く消す設定にしていても、結果が残る。運用の文書と 7 章に、このことを書く。

紐付いたスナップショットは、最も長くて「インシデントを解決してから `INCIDENT_RETENTION_DAYS`」まで残る。`INCIDENT_RETENTION_DAYS` が 0 のときは、紐付いたスナップショットも消えない。インシデントが消えると紐付けも消え、作成から 90 日を過ぎたスナップショットは、次の削除で消える。同じ実行で消えるよう、`purge_retention` では、インシデントの削除をスナップショットの削除より先に行う。

解決から 89 日目に紐付けたスナップショットは、翌日にインシデントと一緒に削除の対象になる。紐付けを外したスナップショットも、次の削除で、通常の規則に従って消える。画面で紐付けを外すときに、このことを確認の文に出す。

PostgreSQL では、紐付けと保持期間による削除が順番に進むよう、インシデントの行を先に処理してから `incident_snapshots` を表ロックする。削除側は別の文でロックを取ってから行と結果を削除するので、先に確定した紐付けが見える。

### 結果の無いスナップショットは紐付けない

自動のスナップショットと、条件を送らずに保存した手動のスナップショットは、結果を持たない。紐付けても、7 日を過ぎると条件しか残らず、インシデントの記録として役に立たない。そのため `no_result` で断る。アラートの発火を記録したいときは、通知履歴の行を紐付ける。

## 5. 画面（PR C）

### インシデントのタブ

「タイムライン」の後ろに「インシデント」のタブを足す。`MainTabId` とタブのアイコン（`components/main-tab-icons.tsx`）も足す。ハッシュは `#/incidents`、詳細は `#/incidents/<id>`。

タブを切り替えると、アプリは `replaceAppHash` でハッシュを `#/incidents` に書き換え、詳細の id が消える（`hooks/useAppTabHashSync.ts:35-40`、`routing/appHashRouting.ts:73-78`）。そのため、タイムラインが表示中に自分のハッシュを書き戻すのと同じく（`hooks/useTimelineViewController.ts:306-331`）、インシデントのパネルが詳細の id を自分で持ち、ハッシュを読み書きする。

- パネルは、表示中に、開いている詳細の id をハッシュに書き戻す。タブを離れて戻ったときも、同じ詳細を開く。
- 一覧から詳細を開くときは、履歴に積む（`location.hash` に代入する）。ブラウザの「戻る」で一覧に戻れる。そのほかの書き戻しは `replaceState` で行う。
- `hashchange` で id が変わったら、その詳細を読み込む。id が無ければ一覧を出す。詳細が 404 なら「インシデントが見つかりません」と出して一覧に戻る。

タブが 10 個になるので、`.tabs` に `overflow-x: auto` を足し、幅が足りないときは横にスクロールさせる。`.tabs` は `position: sticky` で、ボタンの下線は `::after` と `margin-bottom: -1px` で描いている（`App.css:154-196`）。`overflow-x` を足すと縦方向も auto の扱いになり、下線が切れたり縦のスクロールバーが出たりするおそれがある。1,280 px と狭い幅で撮り、1 行に収まるか、下線とスクロールバーの見え方を確かめる。

- **一覧:** 状態の絞り込み（既定は未解決）、件名の検索。列は、件名・状態・重大度・担当・開始の時刻・最終更新・紐付けの件数。operator 以上には「インシデントを作る」を出す。
- **詳細:** 上から順に置く。
  - 件名・状態・重大度・担当・開始の時刻。operator 以上は編集できる。担当には「自分」ボタンを付ける。認証を無効にしているときは、`anonymous` が入るだけなので出さない。保存で 409 が返り、`X-VEA-Error-Code` が `incident_stale` のときは、「ほかの人が更新しました。読み直してください」と出す。
  - 要約（原因と対応）。
  - 経過。メモと自動の記録を古い順に並べる。operator 以上はメモを足せる。admin には各行に「削除」を出す。削除した行は「（〇〇が削除しました）」と出す。
  - 紐付けたイベント（写し）、通知（写し）、スナップショット。それぞれに「外す」ボタン。
  - イベントと通知の写しには、`source_exists` が真のとき「前後 30 分のタイムライン」のリンクを出す（`timelineEntryHash`）。偽のときは「元の行は削除されています」と出す。消えた理由（保持期間、vCenter の削除など）は、サーバでは分からないので書かない。
  - スナップショットには、[案 10](2026-11-24-investigation-export.md) の出力の操作と、「タイムラインで開く」を付ける。

### 「タイムラインで開く」

タイムラインのハッシュは条件だけを扱い、表示中に条件で書き戻すので、スナップショットの指定を足すと消えてしまう。そのため、「グラフで開く」と同じく、ハッシュを使わずにアプリの状態で渡す。

- `App.tsx` に、開くスナップショットの ID と `nonce` を持つ状態を足し、タイムラインのタブに切り替える。
- タイムラインは、この値が変わったら、スナップショットの詳細を取得し、一覧から選んだときと同じ処理で保存した結果を表示する（`hooks/useTimelineSnapshots.ts` の選択の処理と、`hooks/useTimelineViewController.ts` の保存した結果の表示）。
- 表示した後は、通常どおり条件でハッシュを書き戻す。再読み込みすると、保存した結果ではなく条件での表示に戻る（一覧から選んだときと同じ）。
- 詳細が取得できない（404）ときは、タイムラインのエラーの欄に「スナップショットを開けませんでした」と出す。保存した結果が今のスキーマで読めないときは、一覧から選んだときと同じく、保存した条件で再集計して注記を出す（`hooks/useTimelineViewController.ts:77`）。

### 「インシデントに追加」

次の画面の行に「インシデントに追加」を付ける（operator 以上）。押すと、未解決のインシデントを選ぶか、新しく作るかの小さな画面を出す。

- **イベントのタブ:** イベントの行。`occurred_at` も送る。
- **通知履歴:** 通知の行。「インシデントを作る」も付け、件名をルール名と対象から下書きする。
- **タイムライン:**
  - 種類が `event` と `alert` の行。行の時刻を `occurred_at` として送る。まとめた行（件数が 2 以上）は、先頭の 1 件だけを追加し、小さな画面に「まとめた N 件のうち、先頭の 1 件を追加します」と出す。
  - 構成変更と障害パターンのカード。カードが持つ `event_ids`（最大 20 件）を、カードの期間（`first_utc` から `last_utc`）を範囲として添えて追加する。`event_count` の方が多いときは「N 件のうち、先頭の 20 件を追加します」と出す。
  - スナップショットの一覧の行。「結果あり」の行だけに出す。

追加の結果は、ID ごとの結果（3 章）を数えて「2 件を追加しました。1 件は見つかりませんでした」のように出す。

### シードとスクリーンショット

スクリーンショット用のシード（`dev/screenshot_e2e_seed.py`）に、未解決と解決済みのインシデントを 1 件ずつ足す。

## 6. PR の分け方

### PR A: 本書

本書と、10 案の 5 章の「#7」の項目の更新（保持期間はスナップショットに合わせる、という記述を本書の 4 章に合わせる）。

### PR B: 表・移行・API・保持期間の削除

- 移行は 1 本にし、5 つの表と制約と索引を作る。今の head は `b1c2d3e4f5a6` で、実装のときに確かめ直す。
- モデル、スキーマ、ルーター、写しと紐付けを扱うサービス（`services/incidents.py`）、通知の解決の切り出し（`services/alert_history_read.py`）。
- `INCIDENT_RETENTION_DAYS` の設定。0 または 1 以上。
- 保持期間の削除: インシデントの削除を足し、スナップショットの 2 つの削除に条件を足す。`purge_retention` の順序を変える。
- テスト。ファイルは `tests/test_incidents_api.py` と `tests/test_incident_retention.py` に分け、移行は `tests/test_db_session_migrations.py` に足す。
  - 作成・更新・409（`incident_stale`）・削除のロール（viewer は読めるだけ、operator は削除できない）。
  - PATCH の null と省略の区別、`resolved_at` の付け外し。
  - 紐付けの ID ごとの結果（`added`・`already_linked`・`not_found`・`no_result`・`limit_exceeded`）。`occurred_at` が違うとき、範囲の外のときの `not_found`。時刻の確認が無い項目の 422。要求の中の重複。101 件で 422。
  - 写しが、元の行を消した後も読めること。本文とコメントの切り詰め。`source_exists`。
  - 経過の自動の記録（何も追加できなかった要求では書かない）、経過の削除、メモの上限での 409（`incident_entry_limit`）と、上限に達しても PATCH と解除ができること。
  - 紐付いたスナップショットが、行の削除と結果だけの削除の両方で残ること。インシデントが消えた次の削除で、スナップショットが消えること。
  - インシデントの保持期間（未解決は消えない、解決から戻すと消えない、0 で消えない）。
  - 通知履歴の API の応答が、切り出しの前と変わらないこと（既存のテストが通ること）。
- PostgreSQL のテスト: 移行、外部キーの CASCADE、SAVEPOINT を使う紐付け（同じ ID を 2 回送る、削除済みのスナップショット）、`NOT EXISTS` を含む 2 つの削除を、PostgreSQL でも流す。紐付けが先の場合と保持期間の処理が先の場合の両方で表ロックの待ちと処理結果を確かめ、advisory lock が取得できないと保持期間の処理を見送ることも確かめる。テストの名前に `incident` と `postgres` を入れ、`VEA_TEST_POSTGRES_URL` の仕組みを `tests/test_log_pattern_ledger.py` に倣って持たせる。`ci.yml` では、移行のテストを手順 1 に、2 つの新しいファイルを手順 2 に足し、両方の `-k` に `incident` を足す。
- 文書: `docs/operations/backend-operations.md`（保持期間、紐付いたスナップショットの扱い、大きさの最大、SQLite と PostgreSQL での待ち）、`.env.example`、`docs/features/features_list.md`（表の一覧）。

### PR C: 画面と文書

- インシデントのタブ（一覧と詳細）、ハッシュ、zod のスキーマ、タブのアイコン、タブの列の横のスクロール。
- 「インシデントに追加」の小さな画面と、イベント・通知履歴・タイムラインへの組み込み。
- 「タイムラインで開く」のアプリの状態。
- シード、アプリ内ヘルプ、ユーザーガイド（`docs/userguide/incidents.md` を新しく作り、`timeline.md`・`alerts.md`・`events.md` から案内する）、CHANGELOG。

## 7. 個人に関する情報と保存の期間

インシデントには、次の個人に関する情報が入る。

| 情報 | 入る場所 |
|---|---|
| 作った人・変更した人・紐付けた人・メモを書いた人・削除した人の名前 | インシデント、経過、紐付けの行 |
| 担当 | インシデント |
| イベントを起こした利用者名（`user_name`） | 紐付けたイベントの写し |
| イベントの本文（利用者名や IP アドレスを含むことがある） | 紐付けたイベントの写し |
| イベントのコメント（写した時点） | 紐付けたイベントの写し |
| メモの本文、変更の自動の記録（変更前の件名や担当を含む） | 経過 |

- **画面:** viewer も含め、ログインした利用者は全員が読める。スナップショットと同じ扱いである。
- **チャット（LLM）:** 渡さない。
- **保存の期間:** 未解決のあいだは消えない。解決してから `INCIDENT_RETENTION_DAYS`（既定 90 日）で消える。0 にすると消えない。解決した後に紐付けやメモを足しても、期間は延びない。
- **元のデータとの関係:** 写しは、元のイベントの保持期間（7 日）とは関係なく残る。vCenter やアラートルールを削除して元の行が消えた後も、写しには残る。
- **スナップショット:** 紐付いたスナップショットは、結果ごと、インシデントが消えるまで残る。`INCIDENT_TIMELINE_SNAPSHOT_RESULT_RETENTION_DAYS` で結果を早く消す設定も、紐付いたものには効かない。`INCIDENT_RETENTION_DAYS` が 0 なら、紐付いたスナップショットも消えない。
- **消したいとき:** admin は、経過の行を 1 件ずつ消すか、インシデントごと消せる。operator 以上は紐付けを外せば、その写しを消せる。

## 8. 範囲外（後続）

- ログとメトリクスの紐付け。ログも 7 日で消えるが、行の数が多く、写し方を別に決める必要がある。
- イベントの関連する対象（`event_entities`）の写し。写すのは主な対象だけである。
- インシデント単位の出力（案 10 との組み合わせ）。報告書に、経過と写しと、紐付けたスナップショットの結果をまとめる。
- アラートの発火で自動で作ること、同じルールと対象の発火を自動でまとめること。
- チャット（LLM）の文脈にインシデントを入れること。
- 案 9 の対応手順を、インシデントの経過に結び付けること。
- 改ざんの検知や、監査用の記録。

## 9. リスク

- **PostgreSQL での待ち:** 保持期間の処理が `incident_snapshots` を `SHARE` でロックすると、紐付け・解除・インシデントの削除（CASCADE）・`snapshot_ids` 付きの作成は、保持期間の処理のトランザクション全体が終わるまで待つ。保持期間の処理が `SHARE` の取得を待っている間も、新しい書き込みはその後ろに並ぶ（4 章）。
- **SQLite での待ち:** `purge_retention` は全体を 1 つのトランザクションで書く。そのあいだの書き込みの要求は、待ち時間の上限（30 秒）まで待つことがある。30 秒を超えると「database is locked」で 500 になる。運用の文書に書く。
- **解決しないインシデントが残り続ける:** 未解決のインシデントは消えないので、写しと紐付いたスナップショットも残る。一覧の既定を未解決にし、古いものが目に入るようにする。
- **id の再利用:** 写しの重複は自然キーで判定するので、SQLite で id が再び使われても、別のイベントを同じものとは見なさない。紐付けの要求には、ID ごとに時刻か期間を必ず添えるので、古い画面や保存したスナップショットの結果の id が別の行を指しても写さない。すり抜けるのは、再び使われた id の行が、カードの期間の中の発生時刻を持つときだけである。遅れて取り込まれたイベントが、古いカードの期間に重なるときに限られるので、受け入れる。
