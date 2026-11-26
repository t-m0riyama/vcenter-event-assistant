# バックエンドガイド

本ドキュメントは、vCenter Event Assistant のバックエンドを **最短で把握して運用・改修に着手することを目的** としています。対象読者は、開発者と運用担当者の両方です。

## 0. この文書の位置づけ

- [`docs/development/backend.md`](backend.md): バックエンド全体の把握（本ドキュメント）
- [`docs/development/development.md`](development.md): 開発者向け手順（テスト、ツール、LLM詳細など）
- [`docs/operations/backend-operations.md`](../operations/backend-operations.md): 運用（監視、障害対応、変更管理）
- [`docs/development/backend-internals.md`](backend-internals.md): 開発者向けの詳細解説（機能を追加・変更するためのガイドなど）

## 1. 役割と構成

バックエンドは FastAPI を中心に、次を担います。

- `/api` の HTTP API 提供
- vCenter からのイベント・メトリクス・インベントリの収集（pyVmomi）
- 永続化（SQLAlchemy async + PostgreSQL/SQLite）
- 定期ジョブ実行（APScheduler）
- ダイジェストと期間チャットの LLM 連携（任意）

主な実装起点:

- アプリ起動: `src/vcenter_event_assistant/main.py`
- 設定: `src/vcenter_event_assistant/settings.py`
- ジョブ: `src/vcenter_event_assistant/jobs/scheduler.py`
- ルーター: `src/vcenter_event_assistant/api/routes/`
- サービス層: `src/vcenter_event_assistant/services/`

## 2. 主要 API クイックリファレンス

`main.py` で `/api` 配下に各ルーターが登録されています。代表 API は次のとおりです。

### 2.1 システム・設定

- `GET /health`  
  ヘルスチェック（`{"status":"ok"}`）。
- `GET /api/config`  
  保持日数やサンプリング間隔などの公開設定を返します。

### 2.2 vCenter 管理

- `GET /api/vcenters`
- `POST /api/vcenters`
- `GET /api/vcenters/{vcenter_id}`
- `PATCH /api/vcenters/{vcenter_id}`
- `DELETE /api/vcenters/{vcenter_id}`
- `GET /api/vcenters/{vcenter_id}/test`  
  登録済み vCenter への接続テストを実行します。

### 2.3 イベント・メトリクス

- `GET /api/events`  
  フィルタ付きイベント一覧（`total` を含む）。利用者向けの説明は [events.md](../userguide/events.md)。
- `PATCH /api/events/{event_id}`  
  イベントへのユーザーコメント（運用メモ）更新（利用者向けは上記 events.md）。
  イベント一覧の `items`、コメント更新の応答、ダッシュボードの `top_notable_events` はいずれも、主な対象の `entity_name`、`entity_type`、`entity_moid` を含む。moid が保存されていない場合、`entity_moid` は `null` になる。
- `GET /api/events/event-types`  
  イベント種別一覧。
- `GET /api/events/rate-series`  
  指定イベント種別の時系列件数。
- `GET /api/logs`
  保存済みログのフィルタ付き一覧（`limit` は最大200件、`offset` と `total` あり）。
- `GET /api/logs/export.csv`
  同じフィルタに一致する全ログを1回のHTTPリクエストでCSVダウンロード。`time_zone` はIANAタイムゾーン（省略時UTC、画面からは表示設定のTZを送信）。2,000件ずつ時刻・IDのカーソルで取得し、COUNTや深いOFFSETを使わず送信する。ログの内容など外部から入り得る文字列の列は、`=` `+` `-` `@` タブ・CR・LF と全角の `＝` `＋` `－` `＠` で始まるとき先頭に `'` を付ける（CSV injection 対策。時刻・オフセット・数値の列は対象外）。
  CSVはUTF-8 BOM・CRLF。日時列は選択TZの `YYYY/MM/DD HH:mm:ss`、末尾の `time_zone` と `utc_offset` にTZ名と発生基準時刻 `effective_at` 時点のオフセットを記録する。
  開始後の追加ログを除外し、取得前に削除されたログは許容する。各バッチ取得後にDBセッションを閉じる。途中障害では転送を終了し、部分ファイルが残る場合は再ダウンロードする。
- `GET /api/metrics/keys`  
  メトリクスキー一覧。
- `GET /api/metrics`  
  メトリクス系列（`total` と `X-Total-Count` を返却）。利用者向けの説明は [graph.md](../userguide/graph.md)。
- `GET /api/dashboard/summary` — 利用者向けの説明は [summary.md](../userguide/summary.md)  
  直近24hの集約サマリー。

### 2.4 ルール・ガイド・アラート

- `GET/POST/PATCH/DELETE /api/event-score-rules`
- `POST /api/event-score-rules/import`
- `GET/POST/PATCH/DELETE /api/event-type-guides`
- `POST /api/event-type-guides/import`
- `GET /api/event-patterns`
  組み込みの障害パターンの一覧。viewer 以上で参照できる。各定義は `id`、`title`、`description`、`level`、`kind`、`steps`（段ごとの `event_types`）、`within_minutes`、`min_count`（sequence は `null`）を持つ。
- `GET/POST/PATCH/DELETE /api/alerts/rules`
- `POST /api/alerts/rules/import`
- `GET /api/alerts/history`
- `POST /api/alerts/states/resolve`（イベントスコア型・障害パターン型）

通知履歴の `entity_moid` は、`metric_threshold` の `context_key` が `{vcenter_id}:{entity_moid}` 形式のときに入る。対象名を解決できない場合も返す。旧形式のキーや `event_score` の通知では `null` になる。

`event_pattern` の通知履歴とタイムラインのアラート行は、`context_key` から `vcenter_id` と `entity_moid` を取り出す。対象名は、組ごとに `events.occurred_at DESC, events.id DESC` で最新の `event_entities` の行からまとめて引く。保持期間などで名前を引けないときは `null` になる。

アラートルールは `alert_level`（`critical` / `error` / `warning`）を持ち、メール通知の件名・本文および `alert_history` の各行に、通知時点のレベルが記録される。既存 DB はマイグレーションで `warning` を既定とする。イベント行の `severity`（VMware 由来）とは別の運用重大度である。

アラートルールの一覧・作成・更新レスポンスには、不透明な UUID の `revision` が入る。`PATCH /api/alerts/rules/{id}` の JSON 本文には、編集の基準にしたルールから取得した `revision` を含める。欠落や形式違反は `422`、更新対象が削除済みなら `404` を返す。版が古い場合は `409` と `X-VEA-Error-Code: alert_rule_stale` を返すので、最新の内容を読み直して変更を確認する。名前の重複も `409` になる。`config` を送ると種類に応じて検証し、設定全体を置き換える。

ルール保存とインポートの上書き時には新しい版を発行する。エクスポート／インポートでは従来の JSON 形式を使う。

#### 定期アラート評価（トラブルシュート）

利用者向けの説明（画面操作・メールの読み方・FAQ）は [alerts.md](../userguide/alerts.md) を参照する。要注目スコアとスコアルールの設定は [score-rules.md](../userguide/score-rules.md) を参照する。

- バックグラウンドジョブ `evaluate_alerts` は `ALERT_EVAL_INTERVAL_SECONDS`（既定 60 秒）ごとに動く。ログの `executed successfully` は **例外がなかったこと** を示し、必ずしも発火したとは限らない。
- **有効な AlertRule が 1 件以上**必要（設定 → アラート、有効チェック ON）。
- `metric_threshold` ルールの `config.metric_key` は、DB に保存されるキーと **完全一致** させる（CPU 利用率の例: `host.cpu.usage_pct`）。`GET /api/metrics/keys` またはグラフタブのキー一覧を参照する。UI 旧既定の `cpu.usage.average` ではサンプルにヒットしない。
- `metric_threshold` の `AlertState.context_key` は **`{vcenter_id}:{entity_moid}`** 形式（vCenter 間の MoRef 衝突を避ける）。鮮度上限（`METRIC_STALENESS_WINDOW_SECONDS`、未設定時は `PERF_SAMPLE_INTERVAL_SECONDS * 3`）を超えたサンプルは評価対象外。`firing` 中に鮮度切れすると **`stale`** へ遷移し、初回のみ通知する。
- 発火の確認は **通知履歴**（`GET /api/alerts/history`、画面の「通知履歴」タブ）。評価で状態と通知履歴・永続送信予定を同時に保存し、別の配送ジョブが送信・再送する。メールは `SMTP_HOST` と `ALERT_EMAIL_TO` が設定されているときのみ送信される（未設定時は `channel=none`, `success=null` として履歴に記録される）。
- 評価完了時に INFO ログ `alert evaluation complete rules_enabled=N firings=M resolutions=R` が出る。`firings=0` が続く場合は閾値・キー・収集データを見直す。
- 既に `firing` 状態の metric ルールは、条件が続いても **新規通知は出ない**（エンティティごとの状態更新のみ）。回復後に再度閾値超えで firing する。
- **`event_score` ルール**（利用者向けの挙動の正本は [alerts.md](../userguide/alerts.md)。本節は実装・トラブルシュート用の補足）
  - 判定はイベント一覧と同じ DB 列 `notable_score >= config.threshold` かつ `occurred_at >= now - ALERT_EVENT_EVAL_LOOKBACK_HOURS`（**全ルール共通**。ルール `config` に lookback はない）。
  - ウィンドウは `.env` の `ALERT_EVENT_EVAL_LOOKBACK_HOURS`（1〜168、既定 1）。**アプリ再起動**で反映。`ALERT_SNAPSHOT_LOOKBACK_HOURS`（スナップショット用・既定 2）とは別。
  - `config` は `threshold`（必須・0〜100）と `cooldown_minutes`（任意、既定 10）。JSON インポートで `threshold` が文字列でも評価側で数値化する。レガシー `min_notable_score` は `threshold` として読む。
  - 状態は **`event_type`（イベント種別）ごと** の `AlertState` を持ち、通知の Resource / `context_key` は **イベント種別名** である。`cooldown_minutes` は **同一種別へのメール再送の最短間隔（再通知間隔）のみ** に用いる。`last_notified_at` 等と組み合わせ、**間隔未満の再送を抑止** する。
  - **沈黙やウィンドウの切れ目だけで `resolved`（自動回復）にはしない**。`event_score` 型は当面 **自動 resolve を実装しない**（通知履歴画面の解消ボタンで手動 resolve する）。
  - ログに `Error evaluating rule` や `invalid config` が出ていないか確認する。

- **`event_pattern` ルール**
  - `config` は `{"pattern_ids": ["host-conn-flapping"], "cooldown_minutes": 10}` の形。ID の空配列は将来追加されるものを含む全パターンを選ぶ。作成・PATCH・インポートは未知の ID を 422 で拒否する。
  - `alert_event_eval_lookback_hours` の評価期間にパターンの時間幅を足して材料を読み、評価期間内のイベントを使った検知を対象にする。状態のキーは `{vcenter_id}:{entity_moid}:{pattern_id}`。最初と最後のコロンで分ける。
  - `fired_at` は最後に通知または吸収した検知の `last_utc`。発火中は `last_notified_at` から再通知間隔を過ぎ、検知がさらに伸びたときだけ再通知する。解消後は `fired_at` より新しい検知で発火する。
  - 検知が評価期間から外れたときやパターンの選択を外したときは、通知せずに解消する。上限超過・未知の ID で判定を見送ったパターンには警告を記録し、状態を維持する。手動解消は回復通知を登録する。
  - 自動スナップショットの `trigger_id` が 128 文字を超える場合は、先頭 111 文字と `_` に、元の `context_key` の SHA-256 の先頭 16 桁をつなぐ。

### 2.5 収集・ダイジェスト・チャット

利用者向けの説明（本文の読み方・画面操作・FAQ）は [digests.md](../userguide/digests.md) を参照する。

- `POST /api/ingest/run`  
  有効な全 vCenter に対して手動インジェストを実行。
- `GET /api/digests`
- `GET /api/digests/{digest_id}`
- `POST /api/digests/run`  
  ダイジェストを手動生成。
- `POST /api/chat`
- `POST /api/chat/preview`  
  期間コンテキスト付きチャットとプレビュー。利用者向けの説明は [chat.md](../userguide/chat.md) を参照する。

### 2.6 タイムライン

`POST /api/incident-timeline/view` は、期間内の出来事とハイライトを返す。対象の絞り込みに使う要求の項目は次のとおり。

- `entity_moid` は省略できる。前後の空白を除いたあとの上限は 256 文字で、空なら未指定として扱う。指定する場合は `vcenter_id` が必要で、無ければ `422` を返す。
- `entity` は省略でき、上限は 1024 文字。moid を指定しないときは名前の部分一致に使う。moid を指定したときは、moid の無いイベントとログの名前の完全一致に使う。いずれも大文字と小文字を区別しない。

`highlights.top_entities` の各要素の `entity_moid` は、vCenter と moid で数えた対象に入る。名前だけで数えた対象では `null` になる。手動スナップショットの `view_request` にも `entity_moid` を保存できる。

要求の `sources` に `event` が入ると、ハイライトに障害パターンの判定結果を返す。

- `detected_patterns` は最大 20 件。各検知は `pattern_id`、`title`、`description`、`level`、`vcenter_id`、`vcenter_name`、`entity_moid`、`entity_name`、`entity_type`、`first_utc`、`last_utc`、`event_count`、`event_ids` を持つ。レベル、`last_utc` の新しい順、パターン ID、vCenter ID、moid の順で、各 `event_ids` は時刻順の先頭 20 件を返す。
- `detected_patterns_total` は上限で切る前の件数。
- `omitted_patterns` は対象の子表との結合が 10,000 行を超え、判定を省いたパターンの ID。

保存済みの結果にこれらの項目が無ければ、件数は 0、一覧は空配列になる。

判定は各パターンの時間幅だけ期間の起点より前からイベントを読み、期間内のイベントを含む検知を返す。対象の絞り込みは子表の `entity_moid` を使い、名前だけが指定された場合は判定後に `entity_name` に部分一致を当てる。`min_score` に関わらず判定する。

`highlights.config_changes` の各カードは、グループに含まれる対象の構成差分を `diffs` に、上限適用前の件数を `diffs_total` に返す。イベントと観測の時計のずれを見込み、`changed_after < last_utc + 2 分` かつ `observed_at > first_utc - 2 分` の差分を最大 10 件返す。10 件目が装置の入れ替わりの削除行なら、対の追加行も返す。

カードに vCenter または対象の moid が無い場合、その vCenter で構成収集が成功していない場合、カードの `last_utc` が `recorded_since` より前の場合、または差分の項目を持たない保存済み結果では `diffs` は `null`、`diffs_total` は 0 になる。判定した結果が 0 件なら `diffs` は空配列になる。構成収集を無効にしても保存済みの差分は添付される。

#### 調査資料の出力

どちらの API も viewer 以上で使える。

- `GET /api/incident-timeline/snapshots/manual/{id}/export` は保存した結果を出力する。スナップショットが無ければ 404、結果が無いか現在のスキーマで読めなければ 409（`X-VEA-Error-Code: snapshot_result_missing`）を返す。
- `POST /api/incident-timeline/export` は `/view` と同じ本文を受け付け、同じ条件で集計し直す。集計の 400・422・503 はそのまま返す。詳細は 2,000 文字で切って印を付ける。ZIP に入れる結果の JSON が 8 MiB を超えると 413 を返す。
- クエリの `format` は `md` または `zip`。任意の `time_zone` は IANA タイムゾーン名で、既定は UTC、上限は 128 文字。不正な指定には 422 を返す。応答には `Content-Disposition: attachment` と `Cache-Control: no-store` が付く。
- Markdown は注目すべき出来事を最大 100 件載せる。ZIP には `report.md`、表示範囲の `items.csv`、俯瞰の `overview.csv`、`result.json`、`conditions.json` が入る。CSV は UTF-8 の BOM 付きで、時刻ごとに UTC からのずれを別の列に持つ。

保存した結果を読み出すとき、DB から受け取った `result_payload` の JSON の解析はイベントループ上で行う。解析後のスキーマ検証と資料の生成は別スレッドで行う。

報告書は GFM（GitHub・GitLab）と CommonMark 向け。Jira のウィキ記法や Redmine の Textile に貼るときはコードブロックに入れるか、ファイルを添付する。貼り付け先の文字数上限を超える場合も添付する。資料には vCenter・ホスト・VM の名前や moid、イベントとログの内容などが含まれるため、外部に渡す前に中身を確認する。出力したファイルはアプリの保持期間を過ぎても残る。

### 2.7 インベントリ

各 API は viewer 以上で参照できる。

- `GET /api/inventory/impact` は `vcenter_id` と `entity_moid` が必須。任意の `at` は UTC にそろえる。現在時刻と `last_success_at` の遅い方を上限とし、省略時はその上限を使う。指定値が上限を超える場合も、その時刻に丸める。関係は `valid_from <= at < valid_to` の区間で有効で、`valid_to` が空なら開いたままとみなす。
- 応答の `target` は `moid`、`entity_type`、`name` を持つ。対象の種別は収集した値を優先し、収集した値が無ければ同じ vCenter と moid の最新のイベント対象の種別を使う。名前は現在の収集値を使い、空なら moid を返す。
- 未登録の vCenter は 404。ほかの結果は `status` に、優先順に `unsupported_type`、`not_recorded`、`unknown_target`、`absent_at_time`、`stale`、`ok` を返す。`recorded_since` は最初の成功と保持期限の遅い方で、成功が無いときは `null`。`observed_before` は `at` 以前、`observed_after` は `at` より後の最も近い観測を示す。前の観測が無いか、前の観測から設定間隔の 2 倍を超える場合は `stale` になる。
- `groups` の `relation` は起点から見た相手を示す。ホストは `cluster`、`vms`、`datastores`、`networks`、VM は `hosts`、`cluster`、`datastores`、`networks` を返す。クラスタとデータストア、ネットワークは `hosts`、`vms` を返す。VM のクラスタとクラスタの VM は同じ `at` のホスト関係を経由する。各グループの `items` はASCII の英字を小文字にした表示名、表示名、moid の順で最大 200 件、`total` は上限を適用する前の件数。`removed` は現在の観測で見えないことを示す。`stale` と `absent_at_time` でも一覧を返す。
- `from` と `to` を両方指定すると `changes` を返す。片方だけを指定した場合と、`from` が `to` より後の場合は 422 を返す。対象と直接結ばれた関係のうち、`max(from, recorded_since) < 時刻 <= to` の変化を時刻順に最大 200 件返す。ちょうど `from` の時刻の変化は期間外とし、ちょうど `to` の時刻の変化は期間内とする。`items` の各要素は `kind`、相手の `other`、観測時刻の `at`、`action`（`opened` または `closed`）を持つ。`total` は上限を適用する前の件数。記録を始めた時点の構成は期間の起点として扱う。
- `GET /api/inventory/config-diffs` は `vcenter_id` と `entity_moid` が必須。任意の `from` と `to` は UTC にそろえ、両方を省略すると、現在時刻から構成差分の保持期間を引いた時刻から、現在時刻と最後の構成収集成功時刻の遅い方までを使う。片方だけの指定や `from > to` は 422、未登録の vCenter は 404 を返す。
- 差分は `changed_after < to` かつ `observed_at > from` を満たすものを、観測時刻と ID の降順で最大 200 件返す。切れ目に装置の入れ替わりがある場合は対の行も返す。`total` は上限を適用する前の件数。`target` の種別と名前は、見えなくなった対象も含むインベントリの行から取り、対応する行がなければ最新の差分から取る。
- 応答の `status` は `disabled`、`not_recorded`、`ok` のいずれかで、無効でも保存済みの差分は返す。`recorded_since` は構成を最初に観測できた時刻と保持期限の遅い方。`last_success_at` は直近の構成観測の成功時刻。各項目には種類と項目の表示名、観測区間、変更前後の JSON 値が入る。`old_value` と `new_value` の JSON の `null` は、要素の追加・削除の行（`attribute` が `null`）ではその側に要素が無いことを、項目の差分の行ではその側の値が未設定であることを表す。値の切り詰めがある行では、`truncated` が真になり前後の値が文字列で返る。装置の交換は観測した項目から見分けられない場合がある。
- `GET /api/inventory/status` は収集の設定 `enabled`、`config_enabled`、`interval_seconds`、`timeout_seconds` と、`vcenters` を返す。`enabled` はスケジューラと収集の設定が両方有効なときに真になる。各行には `vcenter_id`、`vcenter_name`、`is_enabled`、収集の日時、直近成功時の件数、`last_error` と `last_warning` が入る。状態の行が無い vCenter も表示され、収集状態の各項目は `null` になる。`config_enabled` はスケジューラ、インベントリ収集、構成収集がすべて有効なときに真になり、各 vCenter の `config_*` 項目に構成の収集状態を返す。

影響範囲は、収集アカウントで見えた範囲を示す。時刻は関係の変化を観測した時点を表す。管理対象が一時的に見えなくなり、その後また見えた場合は、見えなかった期間を管理対象の状態からは判定できない。

## 3. 設定の要点（環境変数）

設定は `settings.py` の `Settings` に集約されています。主な運用項目は次のとおりです。

- DB:
  - `DATABASE_URL`
- 収集・保持:
  - `EVENT_POLL_INTERVAL_SECONDS`（`builtin.vcenter.events` と `builtin.vcenter.tasks` の既定の収集間隔。既定 120 秒）
  - `PERF_SAMPLE_INTERVAL_SECONDS`
  - `INVENTORY_SYNC_ENABLED`, `INVENTORY_SYNC_INTERVAL_SECONDS`, `INVENTORY_SYNC_TIMEOUT_SECONDS`
  - `EVENT_RETENTION_DAYS`
  - `METRIC_RETENTION_DAYS`
- ジョブ:
  - `SCHEDULER_ENABLED`
  - `ALERT_EVAL_INTERVAL_SECONDS`
  - `DIGEST_DAILY_*`, `DIGEST_WEEKLY_*`, `DIGEST_MONTHLY_*`
  - **非推奨（v0.3.0 削除予定）**: `DIGEST_SCHEDULER_ENABLED`, `DIGEST_CRON` — 日次ダイジェスト向けレガシー名。実効値は `effective_digest_daily_*` で新設定と合成される。移行先は `DIGEST_DAILY_ENABLED` / `DIGEST_DAILY_CRON`。レガシーが有効なとき起動ログに WARNING が出る。
- デモ・開発:
  - `MOCK_MODE` — 外部サービスなしで動作（使い方は [mock-mode.md](../userguide/mock-mode.md)）
- ネットワーク・ログ:
  - `CORS_ORIGINS`
  - `VCENTER_HTTP_PROXY`
  - `LOG_LEVEL`, `APP_LOG_FILE`, `UVICORN_LOG_FILE`
- LLM:
  - `LLM_DIGEST_*`
  - `LLM_CHAT_*`
  - `LLM_ANONYMIZATION_ENABLED`
  - `LANGSMITH_*`

値の既定やバリデーションは `settings.py` を一次情報として確認してください。

## 4. 起動と実行の最短手順

前提: Python 3.12+ / `uv` / `.env` 用意済み。

```bash
uv sync --all-groups
uv run vcenter-event-assistant
```

フロント開発を併用する場合は、別端末で `frontend` の Vite 開発サーバーを起動し、`/api` はプロキシ経由でバックエンドへ接続します。詳細は `docs/operations/getting-started.md` を参照してください。

## 5. 運用チェックポイント（最小）

- 起動確認: `GET /health` が `ok`
- 定期ジョブ有効化: `SCHEDULER_ENABLED` が想定どおりか
- 収集確認: `POST /api/ingest/run` で投入件数が増えるか
- 保持ポリシー: `EVENT_RETENTION_DAYS` / `METRIC_RETENTION_DAYS` が運用要件に合うか
- vCenter 接続: `/api/vcenters/{id}/test` の疎通結果
- LLM:
  - 未設定時の挙動（ダイジェスト/チャット）を事前に確認
  - 匿名化有効時（`LLM_ANONYMIZATION_ENABLED=true`）の運用要件を確認

## 6. 実装追跡マップ

バックエンドの主要責務と実装パス:

- 起動・ルーター登録: `src/vcenter_event_assistant/main.py`
- API スキーマ: `src/vcenter_event_assistant/api/schemas/`
- DB モデル: `src/vcenter_event_assistant/db/models.py`
- セッション管理: `src/vcenter_event_assistant/db/session.py`
- ジョブ実行: `src/vcenter_event_assistant/jobs/scheduler.py`
- 収集処理: `src/vcenter_event_assistant/services/ingestion.py`
- チャット処理: `src/vcenter_event_assistant/services/chat_llm.py`
- ダイジェスト処理: `src/vcenter_event_assistant/services/digest_run.py`

### 6.1 インベントリの収集と保存

本体の定期ジョブ `inventory_sync` は、有効な vCenter ごとに、VM、ホスト、クラスタ、データストア、ポートグループを観測する。`collectors/inventory.py` は ContainerView と PropertyCollector を使い、DB セッションの外で属性をページ単位で読む。`services/inventory.py` は読み終えた時刻を UTC で記録し、次の表を一つのトランザクションで更新する。

- `inventory_objects` は vCenter と moid ごとに、最新の名前・種別、最初に見えた時刻、見えなくなった時刻を持つ。名前は vCenter が返すエスケープ済みの値を使う。
- `inventory_relations` は、VM → ホスト、ホスト → クラスタ、VM とホスト → データストアおよびポートグループの履歴を持つ。`valid_from` は開いた観測の時刻、`valid_to` は閉じた観測の時刻で、開いた行は `NULL` とする。
- `inventory_sync_runs` は成功した観測の時刻を持つ。
- `inventory_sync_states` は vCenter ごとの最初と最後の成功、最後の開始と失敗、警告、直近の成功時の件数、`instance_uuid` を持つ。

観測時刻は前回の成功時刻を下限とする。接続先の `instance_uuid` が変わったら、開いている関係を閉じて記録をやり直す。通常の観測では差分だけを開閉し、管理対象も変化した行だけ更新する。テンプレートの VM は収集対象から外す。属性の読み取りに失敗した関係と、未接続の VM・ホストのデータストアおよびネットワークの関係は、両端が見える間は持ち越す。書き込みに失敗した観測はロールバックし、失敗の状態を別のトランザクションで記録する。vCenter を削除すると関連する 4 表の行も消える。

関係が変わった時刻と記録の時刻には、収集間隔と読み取り時間の分だけずれがあり得る。ファイルベースの復元で `instance_uuid` も戻る場合は、同じ接続先として収集を続ける。

影響範囲と収集状態のルートは `api/routes/inventory.py` にあり、応答の形は `api/schemas/inventory.py` で定義する。`services/inventory_impact.py` は指定時刻の関係と前後の観測を読み、影響範囲の状態、一覧、期間内の変化を組み立てる。

## 7. 関連ドキュメント

- 全体アーキテクチャ: `docs/features/architecture.md`
- 利用開始: `docs/operations/getting-started.md`
- 内部実装ガイド（API層中心）: `docs/development/backend-internals.md`
- 開発者向けメモ: `docs/development/development.md`
- チャット機能（利用者向け）: `docs/userguide/chat.md` — 概要・補助: `docs/features/chat.md`
- 現状実装の整理: `docs/plans/2026-03-21-vcenter-event-assistant-as-built.md`
