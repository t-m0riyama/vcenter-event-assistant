# バックエンド運用ガイド

本書は `docs/backend.md` の運用詳細版です。運用者が日次監視と変更作業を安全に実行するための最小手順を定義します。

監視ミドルウェアを利用する際の設定例は **[2.6 監視ミドルウェア非依存の設定例（推奨）](#monitoring-generic-examples)** を参照する。

## 1. 対象範囲

- 日次監視（ヘルス/API/ジョブ/ログ）
- 障害時の一次切り分け（概要）
- 運用設定の確認観点
- 変更管理（事前確認、変更後確認、ロールバック）

## 2. 監視項目（実務向け最小）

この章は、5分以内に実施する日次チェックを想定しています。

一次切り分けや復旧手順は **「3. 障害対応 Runbook」** を参照する。

### 2.1 ヘルスチェック

- 対象: `GET /health`
- 正常サイン: `200` かつ `{"status":"ok"}`
- 要対応サイン: タイムアウト、`5xx`、想定外ボディ

### 2.2 主要 API 疎通

- 対象:
  - `GET /api/config`
  - `GET /api/vcenters`
  - `GET /api/events?limit=1`
- 正常サイン: すべて `2xx`、JSON 構造が破損していない
- 要対応サイン: `5xx` の継続、`4xx` の急増（認証・設定不整合の可能性）

### 2.3 定期ジョブ監視

`SCHEDULER_ENABLED=true` のとき、次のジョブが実行されます（`src/vcenter_event_assistant/jobs/scheduler.py`）。

- `poll_events`（イベント収集）
- `poll_perf`（メトリクス収集）
- `evaluate_alerts`（アラート評価）
- `purge_metrics`（古いデータ削除、6時間ごと）
- `digest_daily` / `digest_weekly` / `digest_monthly`（有効化時のみ）

正常サイン:

- `events ingested ...` / `metrics ingested ...` が周期的に出力される
- `digest created kind=...` が対象スケジュールで出力される

要対応サイン:

- `event poll failed` / `perf poll failed` / `alert evaluation job failed` が連続発生
- 想定時刻に `digest created` が出ない

### 2.4 設定依存の監視ポイント

- 収集周期:
  - `EVENT_POLL_INTERVAL_SECONDS`
  - `PERF_SAMPLE_INTERVAL_SECONDS`
- アラート評価周期:
  - `ALERT_EVAL_INTERVAL_SECONDS`
- ダイジェスト:
  - `DIGEST_DAILY_ENABLED`, `DIGEST_DAILY_CRON`
  - `DIGEST_WEEKLY_ENABLED`, `DIGEST_WEEKLY_CRON`
  - `DIGEST_MONTHLY_ENABLED`, `DIGEST_MONTHLY_CRON`
- 実行停止スイッチ:
  - `SCHEDULER_ENABLED=false` の場合、上記ジョブは実行されない

### 2.5 ログ運用の最小ルール

`src/vcenter_event_assistant/logging_config.py` の仕様:

- `APP_LOG_FILE` 未設定: アプリログは標準エラーのみ
- `UVICORN_LOG_FILE` 未設定: uvicorn ログは標準エラーのみ
- ファイル出力有効時はローテーション:
  - 最大 10MB / ファイル
  - バックアップ 5 世代

運用推奨:

- 本番は `APP_LOG_FILE` と `UVICORN_LOG_FILE` を分離設定する
- `LOG_LEVEL` は通常 `INFO`、調査時のみ一時的に `DEBUG`

<a id="monitoring-generic-examples"></a>

### 2.6 監視ミドルウェア非依存の設定例（推奨）

この節は、特定の監視製品に依存せず、運用者が任意の監視ミドルウェアへ写し替えられる「観測対象と判定条件の例」です。

#### 前提（プレースホルダ）

- `BASE_URL`: 監視対象のベースURL（例: `https://vea.example.com`）
- リバースプロキシ配下では、TLS終端やパスプレフィックスの有無に合わせてURLを調整する

このプレースホルダは **「3. 障害対応 Runbook」** でも同じ意味で使う。

#### A) HTTPプローブ（可用性）

監視対象（例）:

- `GET {BASE_URL}/health`
- `GET {BASE_URL}/api/config`
- `GET {BASE_URL}/api/vcenters`
- `GET {BASE_URL}/api/events?limit=1`

判定条件（例）:

- HTTPステータスが `200`
- 応答時間は環境差が大きいため、まず平常時の分布を計測し、その上で `p95` などのしきい値を設定する
- `/health` は本文が `{"status":"ok"}` であることを任意で検証してもよい

注意:

- 本アプリは `/api` 応答に `Cache-Control: no-store` を付与する（`src/vcenter_event_assistant/main.py`）。中間キャッシュ起因の誤判定は起きにくいが、監視側のキャッシュ設定は無効化を推奨する

#### B) プロセス/サービス死活（稼働）

監視対象（例）:

- アプリケーションプロセスの生存
- リッスンポートの生存（運用で決めた待受ポート）

判定条件（例）:

- プロセスが存在しない状態が継続しない
- 短時間に異常な再起動が連続しない

#### C) ログ監視（ジョブ健全性）

観測先:

- `APP_LOG_FILE` / `UVICORN_LOG_FILE` が設定されていればファイル
- 未設定なら標準エラー（コンテナ運用ならログドライバ側で集約）

`SCHEDULER_ENABLED=true` のとき、次のログパターンを監視する（`src/vcenter_event_assistant/jobs/scheduler.py`）。

成功の目安:

- `events ingested ...`
- `metrics ingested ...`
- `digest created kind=...`

失敗の目安:

- `event poll failed`
- `perf poll failed`
- `alert evaluation job failed`
- `purge failed`
- `daily digest job failed` / `weekly digest job failed` / `monthly digest job failed`

注意:

- `SCHEDULER_ENABLED=false` の場合、上記ジョブは動かないため「ログが出ない」こと自体は異常ではない
- `digest_*` ジョブは `DIGEST_*` の有効化時のみ登録される。無効なら `digest created` は出ない

#### D) DB監視（接続と容量）

監視対象（例）:

- `DATABASE_URL` が指すDBへの接続成功
- SQLite ファイル運用なら、DBファイルのディスク使用量とinode
- PostgreSQL 運用なら、DBディスク使用量と接続数

整合確認:

- アプリの保持設定（`EVENT_RETENTION_DAYS`, `METRIC_RETENTION_DAYS`, `ALERT_HISTORY_RETENTION_DAYS`, `DIGEST_RETENTION_DAYS`, `INCIDENT_TIMELINE_SNAPSHOT_RETENTION_DAYS`）と、DBディスクの増加傾向が矛盾していないかを週次で確認する

**SQLite と PostgreSQL の選び方:**

- **SQLite**（`sqlite+aiosqlite://...`）: 開発・試用・単一ノードの小規模向け。`StaticPool` により DB 接続は実質 1 本で、取り込み・評価・API が直列化されやすい。vCenter を多数登録する本番では **PostgreSQL を推奨**する。
- **PostgreSQL**: 本番・複数 vCenter・同時負荷向け。接続プールと書き込み性能に余裕がある。
- 取り込みトランザクションが長大になると SQLite では API が待たされる。緩和策としてイベント挿入の途中 commit 分割は将来検討（現状は vCenter 単位で 1 トランザクション）。

**パスワード・秘密鍵の暗号化（`VEA_SECRET_KEY`）:**

- 対象は `EncryptedString` の列: vCenter のパスワード（`vcenters.password`）、AD/LDAP のサービスアカウントの bind パスワード（`directory_configs.bind_password`）、プラグインの SSH 秘密鍵（`ssh_credentials.private_key`）。一覧は `db/secret_storage_migration.py` の `ENCRYPTED_COLUMNS`。
- 起動時に `ensure_secret_storage()` が、鍵があれば平文の行を `enc:` 形式へ一括更新する（鍵を後から設定した場合の移行）。鍵がなければ WARNING を出す。
- 鍵は bind 済み Settings または環境変数 `VEA_SECRET_KEY` から解決する（`resolve_vea_secret_key`）。Alembic・単発スクリプトでは **環境変数を設定**してから対象の行に触れる。
- API では `enc:` で始まるパスワード文字列は拒否される。DB 直接投入では `enc:` 始まりの平文が暗号化済みと誤判定されうる（稀な縁ケース）。

#### E) SMTP/メール通知（配信経路）

設定（環境変数名の例）:

- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `SMTP_TIMEOUT_SECONDS`
- `SMTP_CA_BUNDLE`, `SMTP_TLS_VERIFY`
- `ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO`

TLS:

- `SMTP_USE_TLS=true`（既定）では STARTTLS を使い、サーバ証明書とホスト名を検証する。以前のバージョンは検証していなかったので、自己署名や社内 CA の証明書の SMTP では、アップグレード後にメールが届かなくなる
- 社内 CA の証明書なら、`SMTP_CA_BUNDLE` に CA バンドル（PEM）のパスを指定する。未設定なら OS 既定の信頼ストアを使う。指定したファイルがなければ起動しない
- `SMTP_TLS_VERIFY=false` で検証をやめられる。経路上の攻撃者に SMTP の資格情報とアラートの内容を盗み見られるので、検証用の環境だけで使う。本番でも起動は止めず、起動時に WARNING を出す
- 暗黙の TLS（465 番ポート、SMTPS）には対応していない。STARTTLS（587 番など）を使う

配送と再送:

- 評価・手動解消は、アラート状態、通知履歴、送信予定（outbox）を同じトランザクションで保存する。SMTP は独立した配送ジョブで実行する。
- `SCHEDULER_ENABLED=true` が配送にも必要。単一アプリプロセス・単一スケジューラで運用する（複数 worker／レプリカの配送排他は未対応）。
- `ALERT_DELIVERY_INTERVAL_SECONDS=10`、`ALERT_DELIVERY_BATCH_SIZE=20`。期日の来た通知を作成順に直列配送し、SMTP通信中にDBトランザクションは保持しない。
- SMTP送信例外（認証エラーを含む）は、`ALERT_RETRY_INITIAL_SECONDS=60` から倍増、`ALERT_RETRY_MAX_SECONDS=3600` を上限に再送する。作成から `ALERT_RETRY_TTL_SECONDS=86400`（24時間）で打ち切る。設定値は正数で `initial <= max <= ttl`。
- `SMTP_TIMEOUT_SECONDS=10` は個々のブロッキング操作のタイムアウトであり、メール1件の総所要時間の上限ではない。
- 件名・本文・From/To・Message-ID は登録時に固定する。接続先と認証情報は配送時の設定を使う。環境変数の変更は再起動で反映する。
- SMTP または宛先未設定は `channel=none`, `success=null`, `delivery_status=skipped`（未送信）。再送対象にしない。既存の待機通知も配送時に設定が未完備なら未送信で終了する。
- テンプレート描画エラーは失敗履歴を残し、再送しない。スナップショット保存失敗はメール配送を止めずログに残す。メール未設定でも自動スナップショットの保存を試みる。
- SMTP受理後の切断、または送信後の結果保存失敗では重複メールが起こり得る。固定 Message-ID は追跡用であり、重複排除を保証しない。
- 回復・ルール無効化後も確定済みの発火通知は配送する。履歴／ルールの削除は待機中通知も削除するが、送信開始済みメールは取り消せない。
- 再送はアラート状態や event_score の cooldown を更新しない。旧バージョンの失敗履歴は自動再送しない。

監視:

- 通知履歴の `delivery_status` は `pending`（配送待ち）、`retrying`（再送待ち）、`succeeded`、`failed`、`skipped`。再送しても1通知1行を更新する。
- `success` は配送待ち・未送信で null、再送待ち・最終失敗で false、成功で true。`attempt_count`、`last_attempt_at`、`next_attempt_at` を確認する。旧履歴の試行回数は不明（null）。
- `notified_at` は配送待ちでは登録時刻、試行後は最新試行時刻。待機通知は保持期間パージから除外する。
- `alert delivery complete queued=... oldest_age_seconds=... succeeded=... retrying=... failed=... skipped=...` で残件数・最古の待機時間・サイクル内結果を確認する。`failed > 0` は打ち切りの調査対象。
- `Alert delivery failed history_id=...; continuing batch` は配送途中のDB等の異常。後続の配送を続行し、残った送信予定は再試行する。
- `alert notification delivery job failed` と `alert evaluation job failed` はジョブ全体の異常。SMTP未設定の警告も、メール必須運用では監視する。
- 本文・宛先は未配送の間DBに保存される。配送終了時にoutboxを削除し、本文を含まない結果履歴は従来の保持期間で管理する。

## 3. 障害対応 Runbook

### 大量ログのCSV出力

ログタブの収集状況は、タブ表示時・画面復帰時と、表示中の30秒間隔で更新する。収集が復旧すれば過去のエラー表示は消える。別タブ表示中とブラウザの非表示中は状況確認を休止する。状況確認APIが失敗しても保存済みログの検索は継続できる。

ログ画面のCSVはブラウザが直接ダウンロードする。進捗・完了・キャンセルはブラウザで確認する。数百万件でもサーバーと画面で全件を保持しないが、同時ダウンロード数と各ログ本文の大きさによって負荷は増える。

プロキシ経由の導入時は、`/api/logs/export.csv` のストリーミングがバッファされないこと、最初のDB検索と転送中の待ち時間がプロキシのタイムアウト内に収まることを確認する。APIは `X-Accel-Buffering: no` を返すが、実際のプロキシ設定でも確認する。初回更新では `(effective_at, id)` のインデックス作成が走るため、大量データがある環境では起動時の作成時間も確認する。転送中のエラーは `Log CSV export failed after N rows` として記録される。HTTP 200は転送完了を保証しない。

日時列がExcelで文字列になる環境では、CSV取り込み時に年月日形式の日時を指定する。Excelの1シート上限は1,048,576行であり、数百万件のCSVを全行表示するには期間や条件を絞った出力が必要。

再測定は `python scripts/benchmark_log_export.py --rows 2000000` で実行する（環境のPythonにプロジェクト依存が必要）。一時SQLite DBは終了時に削除される。PostgreSQLは `--database-url` に空の検証専用DBを指定する。出力をメモリに蓄積せず、行数・生成サイズ・時間・ピークRSS・バッチ間の検索応答時間を確認する。既存テーブルのあるDBは拒否する。PostgreSQLの検証DBは測定後に削除する。

2026-10-03のローカル検証では、各DBで200万件（395,777,951バイト）のCSVを生成し、ヘッダーを除いた出力件数を確認した。SQLiteは55.02秒、出力開始時から完了までのピークRSSは76.6→77.4MiB。PostgreSQL 16は32.65秒、ピークRSSは77.9MiBで一定だった。時間はデータ作成を除き、DB読み取りとCSV生成を含む。バッチ間の検索は最大3.82ms／3.06ms。ネットワーク転送、実運用の本文サイズや同時負荷、Excelでの日時認識、本番プロキシのタイムアウトはこの測定に含まない。

この章は、障害発生時の一次切り分けと復旧のための手順である。日常点検は **「2. 監視項目」** と **「2.6 監視ミドルウェア非依存の設定例」** を先に実施する。

### 3.1 使い方（このRunbookの読み方）

`{BASE_URL}` は **「2.6 監視ミドルウェア非依存の設定例」** と同じ前提である。

各節は次の型で書く。

1. 症状
2. まず確認すること（ログ/設定/API）
3. よくある原因と対処
4. 復旧確認（同じ手順で再チェック）

### 3.2 アプリが応答しない/遅い

症状:

- ブラウザやクライアントから UI/API が開けない
- 応答が極端に遅い

確認:

- `GET {BASE_URL}/health` が `200` か
- リバースプロキシ配下なら、TLS終端・Upstream・タイムアウト設定を確認する
- `LOG_LEVEL` を一時的に上げ、例外が増えていないか確認する

対処の例:

- プロセス再起動
- Upstream の過負荷や接続枯渇を解消する

### 3.3 収集が進まない（イベント/メトリクスが増えない）

症状:

- 画面のイベント/メトリクスが更新されない
- 手動収集を押しても増えない

確認:

- `SCHEDULER_ENABLED` が意図どおりか（`false` なら定期収集は動かない）
- vCenter が有効か（無効 vCenter は収集対象外）
- `GET {BASE_URL}/api/vcenters/{id}/test` が成功するか
- `VCENTER_HTTP_PROXY` が必要な環境で未設定になっていないか（`src/vcenter_event_assistant/collectors/connection.py`）
- ログに `event poll failed` / `perf poll failed` が出ていないか（`src/vcenter_event_assistant/jobs/scheduler.py`）

対処の例:

- vCenter 資格情報・FQDN・ポート・プロトコルを修正する
- プロキシ設定を修正する
- 一時的に `POST {BASE_URL}/api/ingest/run` を実行し、戻り値の件数とログを確認する

### 3.4 DB障害（接続失敗/遅い/ディスク）

症状:

- API が `5xx` になりやすい
- ログにDB接続エラーが出る

確認:

- `DATABASE_URL` が正しいか（ホスト/ポート/ユーザー/DB名）
- SQLite ファイル運用なら、ディスク空きとファイル権限を確認する
- PostgreSQL 運用なら、接続数・ディスク・インデックス肥大の兆候を確認する
- 保持期間設定（イベント・メトリクス・通知履歴・ダイジェスト・スナップショット）と実データ増加が整合しているか

対処の例:

- DBを復旧させ、接続情報を修正する
- ディスク拡張や不要データ削除（運用ポリシーに従う）

### 3.5 ダイジェストが失敗する/期待と違う

症状:

- ダイジェスト一覧に `status=error` が増える
- 手動実行後も本文が空、または期待した要約が無い

重要な挙動:

- `POST {BASE_URL}/api/digests/run` は **HTTP が成功しても**、保存レコードが `status=error` になり得る（`src/vcenter_event_assistant/services/digest_run.py`）
- レスポンス（`DigestRead`）の `status` / `error_message` / `body_markdown` を必ず確認する（`src/vcenter_event_assistant/api/schemas/legacy.py`）

確認:

- `GET {BASE_URL}/api/digests` で最新の `status` を確認する
- `error_message` が `digest template:` で始まる場合はテンプレート側の問題を疑う
- LLM 要約が期待どおりでない場合は `LLM_DIGEST_*` と `LLM_DIGEST_API_KEY` の有無を確認する
  - `LLM_DIGEST_API_KEY` が空の場合、LLM 呼び出しは行われず、テンプレート本文がそのまま保存される（`src/vcenter_event_assistant/services/digest_llm.py`）
  - LLM 呼び出しに失敗した場合、`status` は `ok_llm_failed`（テンプレート本文は保存済み）となり、`error_message` に省略理由が入る。旧データは `status=ok` のまま `error_message` のみが入っている場合がある

対処の例:

- テンプレートパス/構文エラーを修正する
- LLM 側の疎通・モデル名・タイムアウトを修正する

### 3.6 チャットが使えない/失敗する

症状:

- UI からチャットが送信できない
- 応答が空、またはエラー表示になる

確認:

- `POST {BASE_URL}/api/chat` が `503` になっていないか（LLM未設定時は `503` になり得る: `src/vcenter_event_assistant/api/routes/chat.py`）
- `LLM_DIGEST_API_KEY` / `LLM_CHAT_API_KEY`、または Copilot CLI セッション認証が要件を満たすか
- 200 応答でも `error` フィールドに失敗理由が載る場合がある（LLM失敗など）

追加の切り分け:

- 期間が逆転していないか（`from` は `to` より前である必要がある）
- トークン上限や匿名化設定の影響を疑う場合は `docs/development.md` のチャット節を参照する

### 3.7 メール通知が届かない

症状:

- アラートが発火しているはずだがメールが来ない

確認:

- ログに次が出ていないか（`src/vcenter_event_assistant/services/alerting/notification/email_channel.py`）
  - `SMTP_HOST is not set. Skipping email notification.`
  - `ALERT_EMAIL_TO is not set. Skipping email notification.`
  - `Failed to send email notification: ...`（`certificate verify failed` を含むときは、SMTP サーバの証明書を検証できていない。`SMTP_CA_BUNDLE` を設定する）
- `alert evaluation job failed` が出ていないか（`src/vcenter_event_assistant/jobs/scheduler.py`）

対処の例:

- 通知履歴で配送状態・エラー・試行回数・次回時刻を確認する。配送待ちが増える場合はスケジューラの有効化と配送ジョブログも確認する。
- SMTP 接続先・認証情報・TLS設定を正し、再起動する。再送待ちの通知は期限内なら自動再送される。登録済みの宛先は変更されない。
- 未送信／描画失敗／期限超過は自動再送されない。受信が必須の場合は履歴を確認し、運用者が別経路で内容を伝達する。手動再送APIは未提供。

## 4. 運用設定チェックリスト

日次/週次点検で、少なくとも次を確認します。

- DB: `DATABASE_URL`
- API 待受: `UVICORN_HOST`, `UVICORN_PORT`（ポート未設定時は `8000`）
- スケジューラ有効化: `SCHEDULER_ENABLED`
- APScheduler の `misfire_grace_time`: interval ジョブは各間隔の半分、cron ダイジェストは 3600 秒（`jobs/scheduler.py`）。イベントループ停止後の取りこぼし軽減用
- 保持期間: `EVENT_RETENTION_DAYS`, `METRIC_RETENTION_DAYS`, `ALERT_HISTORY_RETENTION_DAYS`, `DIGEST_RETENTION_DAYS`, `INCIDENT_TIMELINE_SNAPSHOT_RETENTION_DAYS`（いずれも `0` でパージ無効）
- ダイジェスト: `DIGEST_*`
- LLM とトレース: `LLM_*`, `LANGSMITH_*`
- ログ出力: `LOG_LEVEL`, `APP_LOG_FILE`, `UVICORN_LOG_FILE`
- 認証: `VEA_AUTH_ENABLED`（既定 `true`、本番では無効にできない）、`VEA_SESSION_*`、`VEA_LOGIN_*`、`VEA_BOOTSTRAP_ADMIN_PASSWORD` が残っていないこと（起動時に警告）
- プラグイン管理: `VEA_PLUGIN_MANAGEMENT_ENABLED`（既定 `false`）、`VEA_PLUGIN_ALLOW_INDEX_INSTALL`（既定 `false`）、`VEA_PLUGIN_DIR`
- コレクタワーカーのログ: `VEA_COLLECTOR_WORKER_LOG_LEVEL`（未設定時は `LOG_LEVEL` を継承）

## 4.1 プラグイン管理を有効化する場合

`VEA_PLUGIN_MANAGEMENT_ENABLED=true` にすると、`/api/plugins` の変更系 API（設定変更・リロード・
インストール・アンインストール）が開きます。**これは実質的に任意コード実行を許す操作です。**
これらの API は admin ロールだけが呼べます。有効化する場合は次を必ず満たしてください。

- admin ロールは信頼できる利用者だけに付与する（`vcenter-event-assistant-admin list-users` で定期的に確認する）
- `VEA_PLUGIN_ALLOW_INDEX_INSTALL` は原則 `false` のままにし、アップロード経路のみを使う
  （`true` にすると実行時に外部インデックスから取得するため、サプライチェーンリスクが増える）
- `VEA_PLUGIN_DIR` を永続ボリュームに割り当てる（コンテナ入れ替えでインストール済みプラグインが消えないようにする）
- 本番で有効化すると起動時に WARNING が出ます（`security_startup.py`）。ログで有効化を検知できます。

運用手順:

1. **Settings > プラグイン**でパッケージ（`.whl` / `.tar.gz`）をアップロードする
2. 状態が「インストール済み」になるまで待つ（失敗時は同画面にエラーが出る）
3. 対象プラグインを有効化し、必要なら実行間隔・タイムアウトを設定する
4. **変更を反映**を押す（アプリの再起動は不要。レジストリ世代が 1 つ進む）
5. `collector_run_states` またはプラグイン画面の実行状況で、収集が成功していることを確認する

ロールバック: 対象プラグインを無効化して**変更を反映**、または削除して**変更を反映**。
外部プラグインは専用ワーカープロセスで動くため、ハングしても `timeout_seconds` でワーカーが
kill され、アプリ本体は停止しません。

### 4.1.1 プラグインの失敗を調べる

プラグイン画面および `GET /api/plugins/collectors` の `error_message` は、既定では
**例外の型名と定型句だけ**です（例外文言は認証情報やサーバの応答本文を含みうるため）。
`ImportError` 系・entry point 不明・`NotImplementedError`・バッチと manifest の検証エラーの
ように、メッセージが import 機構かワーカー自身からしか生成されない型に限り、メッセージも
表示されます。`KeyError` のようにメッセージがデータそのものになる型は対象外です。

**完全な情報はコレクタワーカープロセスの stderr にあります。** ワーカーの stderr は
親プロセスへ継承されるので、アプリのログをそのまま見れば含まれています。行頭が
`[collector-worker <pid>]` になっているものがワーカー由来です。

詳細を出したいときは `VEA_COLLECTOR_WORKER_LOG_LEVEL=DEBUG` にします。アプリ全体の
`LOG_LEVEL` は変えずに、外部プラグインのログだけを詳細化できます。

よくある失敗:

| `error_message` | 意味 | 対処 |
|---|---|---|
| `ModuleNotFoundError: No module named '...'` | プラグインの依存が入っていない | アップロード導入は `--no-index --no-deps` で実行されるため依存が解決されない。インデックス経由での導入を許可するか、依存を同梱したパッケージを作り直す |
| `load failed: ...` | entry point の読み込みに失敗 | ワーカーの stderr にトレースバックが出ている |
| `TimeoutError: collector execution failed` | `timeout_seconds` 超過でワーカーを kill | 実行間隔とタイムアウトを見直す。ワーカーは次回実行で作り直される |
| `BatchValidationError: ...` | バッチ検証で拒否。違反した規則がそのまま表示される | プラグイン側の修正が必要。条件の一覧は `docs/collector-plugin-authoring.md` の「バッチが拒否される条件」 |

## 4.2 認証を導入したバージョンへの更新

このバージョンから、認証が既定で有効になります（`VEA_AUTH_ENABLED=true`）。更新前に次を準備してください。

1. 初期 admin を用意する（手順は下の「4.2.1 初回起動時の admin の指定」）。本番（`APP_ENV=production`）では admin がいないと起動を止めます
2. HTTPS で配信している場合、`APP_ENV=production` でなければ `VEA_SESSION_COOKIE_SECURE=true` を設定する
3. `curl` などで API を直接呼んでいるスクリプトは、ログインが必要になるため動かなくなります。ログイン API でセッション Cookie を取得して使ってください。POST / PUT / PATCH / DELETE（ログイン自体を含む）には `X-Requested-With: XMLHttpRequest` ヘッダが必要です

   ```bash
   curl -c cookies.txt -H 'Content-Type: application/json' -H 'X-Requested-With: XMLHttpRequest' \
     -d '{"username":"admin","password":"..."}' http://localhost:8000/api/auth/login
   curl -b cookies.txt http://localhost:8000/api/events
   ```

4. リバースプロキシで行っていた認証は、二重になるため外してもかまいません（TLS 終端とネットワーク制限は引き続きプロキシで行う）
5. ログインできたら `VEA_BOOTSTRAP_ADMIN_PASSWORD` を `.env` から削除する
6. アラートメールの STARTTLS で、SMTP サーバの証明書を検証するようになりました。自己署名や社内 CA の証明書の SMTP では、`SMTP_CA_BUNDLE` に CA バンドルを指定してください（検証用の環境なら `SMTP_TLS_VERIFY=false`）。指定しないとメールが届かなくなります（詳細は「E) SMTP/メール通知」）

ログインの失敗・ロックアウト・ユーザー変更は、ロガー `vcenter_event_assistant.audit` に `AUDIT event=...` の形式で出力されます。

### 4.2.1 初回起動時の admin の指定

更新前の DB にはユーザーがいないため、更新後の最初の起動で admin を 1 人作ります。方法は次のどちらかです。

**方法 A: 環境変数で指定する（推奨）**

更新後のアプリを起動する前に、`.env` に次の 2 行を追加します。Docker Compose も `env_file` で同じ `.env` を読みます。

```dotenv
VEA_BOOTSTRAP_ADMIN_USERNAME=admin
VEA_BOOTSTRAP_ADMIN_PASSWORD=ここに12文字以上のパスワード
```

- パスワードは `VEA_PASSWORD_MIN_LENGTH`（既定 12）文字以上にします。短いと起動時にエラーで停止します
- 2 つのうち片方だけを設定した場合も、起動時にエラーで停止します
- `.env` を使わずにシェルで一時的に渡してもかまいません（例: `VEA_BOOTSTRAP_ADMIN_USERNAME=admin VEA_BOOTSTRAP_ADMIN_PASSWORD='...' uv run vcenter-event-assistant`）。シェル履歴に残る点に注意してください
- 起動ログに `Created initial admin user 'admin'` と出れば作成済みです。ブラウザでその名前とパスワードでログインします
- ログインできたら `VEA_BOOTSTRAP_ADMIN_PASSWORD` の行を `.env` から削除します（ユーザーがいる状態で残っていると、起動のたびに警告が出ます）。作成されるのはユーザーが 0 人のときだけなので、あとから値を変えてもパスワードは変わりません

**方法 B: CLI で作る**

アプリを更新したあと、パスワードを対話で入力して作ります。本番（`APP_ENV=production`）は admin がいないと起動しないため、本番では方法 A を使うか、起動前に CLI を実行してください（CLI は起動時と同じく DB を最新のスキーマへ更新してから作成します）。

```bash
uv run vcenter-event-assistant-admin create-user admin --role admin
```

Docker Compose の場合:

```bash
docker compose run --rm app vcenter-event-assistant-admin create-user admin --role admin
```

パスワードを対話入力できない環境では `--password-stdin` を付け、標準入力の 1 行目から渡します。

**パスワードを忘れたとき**

`vcenter-event-assistant-admin reset-password <ユーザー名>` で再設定します（ロックも解除されます）。`VEA_BOOTSTRAP_ADMIN_PASSWORD` を変えても既存ユーザーのパスワードは変わりません。

## 5. 変更管理（実務向け最小）

### 5.1 変更タイプ

- 設定値変更（`.env`）
- スケジューラ関連変更（周期・有効/無効）
- LLM 関連変更（プロバイダ、キー、モデル、匿名化）
- プラグイン変更（インストール・有効/無効・実行間隔）

### 5.2 変更前チェック

- 変更対象の現行値を記録する（ロールバック用）
- 影響範囲を確認する
  - API 応答
  - 定期ジョブ
  - ログ出力
- 影響時間帯を調整する（収集やダイジェスト実行タイミングを回避）

### 5.3 変更実施後チェック

- `GET /health` が正常
- `GET /api/config` が正常
- ジョブログに異常がない
  - `event poll failed`
  - `perf poll failed`
  - `alert evaluation job failed`
  - `daily digest job failed`
  - `weekly digest job failed`
  - `monthly digest job failed`
  - `collector worker timed out`
  - `collector plugin discovery failed`
  - `plugin installation job failed`
- 変更対象のAPIを1つ以上実行し、期待どおりか確認

### 5.4 ロールバック手順（最小）

1. `.env` を変更前の値に戻す
2. アプリケーションプロセスを再起動する
3. `GET /health` を再確認する
4. ジョブログの異常が収束したことを確認する

## 6. 関連ドキュメント

- バックエンド全体入口: `docs/backend.md`
- システム全体像: `docs/architecture.md`
- 開発者向け詳細: `docs/development.md`（チャット/LLM の挙動や環境変数の詳細）
