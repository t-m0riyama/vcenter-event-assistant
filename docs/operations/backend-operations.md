# バックエンド運用ガイド

本書は `docs/development/backend.md` の運用詳細版です。運用者が日次監視と変更作業を安全に実行するための最小手順を定義します。

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
- `inventory_sync`（インベントリの関係を収集。`INVENTORY_SYNC_ENABLED=true` のときに登録）
- `evaluate_alerts`（アラート評価）
- `log_pattern_backfill`（ログの型の埋め戻しと追いつき、5 分ごと。1 回で最大 50,000 行）
- `purge_metrics`（古いログ・型の台帳など、保持期限を超えたデータの削除。既定は 6 時間ごと）
- `digest_daily` / `digest_weekly` / `digest_monthly`（有効化時のみ）

正常サイン:

- `events ingested ...` / `metrics ingested ...` が周期的に出力される
- `digest created kind=...` が対象スケジュールで出力される

要対応サイン:

- `event poll failed` / `perf poll failed` / `alert evaluation job failed` が連続発生
- 想定時刻に `digest created` が出ない
- `log pattern backfill failed` が連続発生

型の埋め戻しは、初回の実行でログの最大 id とその観測時刻を記録する。
記録から 270 秒以上たった実行で境界を確定し、処理を始める。進捗は
`log_pattern_backfill_state` の `last_id` と `upper_id` で見られる。完了すると
`completed_at` が入り、その後も旧コードで取り込まれた行があれば追いつきで型を付ける。

### 2.4 設定依存の監視ポイント

- 収集周期:
  - `EVENT_POLL_INTERVAL_SECONDS`（組み込みのイベントと完了したタスクの収集間隔。既定 120 秒）
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

#### HTTP リクエスト本文の上限

アプリは `Content-Length` が上限を超えるリクエストや、受信中に本文が上限を超えたリクエストに `413 Request body too large` を返します。POST、PUT、PATCH、DELETE では本文を読む際に実バイト数を累計するため、`Content-Length` のない転送にも適用されます。認証や CSRF 検査などで本文を読む前に応答する場合は、その応答が返ります。

- ログインは 64 KiB、通常は 16 MiB。
- プラグインのアップロードは multipart 全体で 51 MiB。ファイル単体の上限は 50 MiB。
- チャットと送信プレビューは、会話履歴と JSON の構造に 49 MiB、添付可能な1件につき最大約 13.34 MiB（画像の標準 Base64 表現に相当）を加算します。添付5件の既定設定では約 116 MiB、最大20件の設定では約 316 MiBです。Base64 を JSON エスケープした場合も、転送時の実バイト数で判定します。認証有効時は、両 API とも本文を読む前に Operator 以上の権限を確認します。

リバースプロキシにも本文上限を設定している場合は、アプリとプロキシの両方の上限が適用されます。

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
- `inventory sync failed`
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

- アプリの保持設定（`EVENT_RETENTION_DAYS`, `METRIC_RETENTION_DAYS`, `ALERT_HISTORY_RETENTION_DAYS`, `DIGEST_RETENTION_DAYS`, `INCIDENT_RETENTION_DAYS`, `INCIDENT_TIMELINE_SNAPSHOT_RETENTION_DAYS`, `INCIDENT_TIMELINE_SNAPSHOT_RESULT_RETENTION_DAYS`）と、DBディスクの増加傾向が矛盾していないかを週次で確認する

- インベントリは `EVENT_RETENTION_DAYS`（既定 7 日）を使う。週次の容量点検では、期限を超えた閉じた関係、見えなくなった管理対象、成功した観測の記録が削除されているかも確認する。開いている関係と見えている管理対象は、収集を停止しても残る。

**ログと型の台帳の保持:**

- `LOG_RETENTION_DAYS`（既定 7 日）でログ本文の保持期間を設定する。
- `LOG_PATTERN_RETENTION_DAYS`（既定 90 日）で、型を最後に見てから台帳に残す日数を設定する。
  `LOG_RETENTION_DAYS` 以上か `0` を指定する。`0` の場合は、期間による削除を行わない。
- `LOG_PATTERN_MAX_PER_VCENTER`（既定 20,000）を超えた場合は、最終観測が古い型から削除する。
  ログの保持期間内の型と、ログにキーが残る型は削除の対象外なので、台帳が上限を超えることがある。
- `LOG_PATTERN_WARMUP_DAYS`（既定 3 日）は、出どころごとの慣らしの期間を設定する。
  埋め戻しの完了後、出どころの台帳を開始した時刻からこの日数が過ぎて初めて警告以上で出た型を判定できる。

台帳には伏せ方を適用した型を保存する。ホスト名や VM 名など、型に残ったログの語は本文の保持期間を過ぎても台帳に残る。
タイムラインの結果に含まれる型は、保存結果の保持期間に従って残り、調査資料にも入る。

**インシデントの保持期間**

`INCIDENT_RETENTION_DAYS`（既定 90 日）は、解決したインシデントの `resolved_at` から数える。未解決のインシデントは自動削除の対象外。解決後に紐付けやメモを足しても期限は延びない。0 で自動削除を無効にする。インシデントの削除に伴い、経過と紐付けも消える。

インシデント 1 件あたり、イベントの写し 500 件で約 10 MB、通知の写し 200 件で約 0.4 MB、メモ 1,000 件で約 12 MB、要約で約 60 KB が上限の目安になる。日本語を UTF-8 で 1 文字 3 バイトとして、合計は約 23 MB。操作の自動記録は 1 行約 2 KB で、件数の上限はない。紐付けたスナップショットの保存結果は 1 件最大 8 MiB、10 件で最大 80 MiB。インシデントの件数に上限はない。

**スナップショットの保存結果の保持期間:**

タイムラインのスナップショットは、保存時に集計した結果（イベント・ログの本文を含む）を持つ。結果の保持は次の 2 つで決まる。

- `INCIDENT_TIMELINE_SNAPSHOT_RETENTION_DAYS`（既定 90）: スナップショットの行ごと削除する。
- `INCIDENT_TIMELINE_SNAPSHOT_RESULT_RETENTION_DAYS`（既定 `0`）: `created_at` からこの日数を過ぎたスナップショットの**保存結果だけ**を消す。`0` は結果だけを先に消さない（行と同じ期間残る）。

結果だけを消したとき、行・保存した条件・運用メモは残る。画面は「結果なし」として、保存した条件で現在のデータから再集計する（元のイベント・ログ・メトリクスが保持期間を過ぎていれば、再集計の結果は空になる）。パージの周期は `PURGE_INTERVAL_HOURS` で、他の保持設定と同じジョブで実行する。行の保持期間より長い値を設定しても害はない（行が先に消える）。

インシデントに紐付いたスナップショットは、行の削除と結果だけの削除の両方から外れる。紐付けがすべて外れた後は、スナップショットの作成時刻を基準に通常の保持期間を適用する。ジョブはインシデントを先に削除するので、期限を過ぎたスナップショットは同じ実行で削除できる。`INCIDENT_RETENTION_DAYS=0` でインシデントを残し続ける場合、その紐付けがある間はスナップショットも残り続ける。

インシデントに紐付いていないスナップショットで、イベント・ログの本文を元データの保持期間より長く残したくないときは、イベント・ログの保持期間に合わせた値（例: `7`）にする。

**SQLite と PostgreSQL の選び方:**

- **SQLite**（`sqlite+aiosqlite://...`）: 開発・試用・単一ノードの小規模向け。ファイル DB ではセッションごとに接続を借り、SQLite が書き込みを DB 単位で直列化する。インメモリ DB では通常のセッションが接続を共有し、アラートルールの更新とインシデントの書き込みは専用の接続で独立したトランザクションを使う。vCenter を多数登録する本番では **PostgreSQL を推奨**する。
- **PostgreSQL**: 本番・複数 vCenter・同時負荷向け。接続プールと書き込み性能に余裕がある。
- 保持期間の削除は 1 つのトランザクションで行う。SQLite で書き込みが 30 秒を超えて待つと、`database is locked` で API が 500 を返す。
- PostgreSQL では、保持期間の処理が `incident_snapshots` を表ロックしている間、スナップショットの紐付けと解除、インシデントの削除（CASCADE）、スナップショットを同時に紐付けるインシデントの作成は、保持期間の処理のトランザクション全体が終わるまで待つ。
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
- Docker では、CA バンドルをコンテナに読み取り専用でマウントし、`SMTP_CA_BUNDLE` にはコンテナの中のパスを指定する（ホストのパスを書いても、コンテナの中にファイルがないので起動しない）。compose のテンプレートはルートファイルシステムが読み取り専用なので、`/data` に置くかマウントする。ファイルはコンテナの実行ユーザー（UID 1000）が読める権限にする。vCenter 用の `VCENTER_CA_BUNDLE` も、コンテナの中のパスを指定する必要がある点は同じ

  ```yaml
  services:
    app:
      environment:
        SMTP_CA_BUNDLE: /etc/vea/smtp-ca.pem
      volumes:
        - ./certs/smtp-ca.pem:/etc/vea/smtp-ca.pem:ro
  ```

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

### 2.7 ログの型の集計

`LOG_PATTERN_SCAN_MAX_ROWS`（既定 500,000 行）は、`GET /api/logs/patterns` の条件に合うログの上限を設定する。上限を超えると HTTP 422（`detail.code` が `log_pattern_scan_limit`）を返す。期間を短くするか、vCenter などの検索条件を追加して対象を絞り込む。

開発機の Docker 上で PostgreSQL 16 を使用して計測した。`log_records` は 605 万行（vCenter 2 台、7 日分、型 1,000 個、全行がキー付き）で、集計上限は 500,000 行とした。

| 処理・条件 | 条件に合う行数 | 所要時間 |
| --- | ---: | ---: |
| 型の集計・12 時間、全 vCenter | 約 43 万行 | 0.64〜1.10 秒 |
| 型の集計・12 時間、vCenter 1 台 | 約 22 万行 | 0.21〜0.27 秒 |
| 型の集計・1 時間 | 約 3.6 万行 | 0.05 秒 |
| 型の集計・1 日 | 約 86 万行 | 0.16〜0.22 秒で HTTP 422 |
| 型の集計・7 日、重大度 `error` | 約 100 万行 | 0.60 秒で HTTP 422 |
| 型の集計・7 日、本文の部分一致 | 1 行 | 1.77 秒 |
| タイムラインの警告以上の行の集計・1 日、`(vcenter_id, pattern_key) IN (...)` で 500 組 | — | 0.20 秒 |

型の集計は `aggregate_log_patterns` を計測した。タイムラインは `ix_log_records_severity_norm_effective` と `BitmapOr` を使う `Bitmap Heap Scan` で実行され、`Seq Scan` は発生しなかった。

- 上限が適用されるのは条件に合う行数。本文の部分一致のように一致する行が少ない条件では、7 日間で 1 行だけ一致した計測と同様に、指定期間内の全行を読んで一致を確かめる。
- `pattern_key` だけを指定すると、索引 `(vcenter_id, pattern_key, effective_at)` の先頭列を絞れず、時間がかかる。vCenter も指定すると、その索引の先頭列で絞れる。

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

#### 本番環境で既存の HTTP 登録を HTTPS に移行する

`APP_ENV=production` では、保存済みの vCenter が HTTP の場合も、接続テストや収集などの vCenter API 接続を拒否する。アップグレード前に「設定 → vCenter」で HTTP の登録を確認し、次の手順で移行する。

1. 対象の接続方式を HTTPS に変更し、実際の TLS ポート（通常は 443）を指定する。
2. 「SSL 証明書を検証（HTTPS のみ）」を有効にする。独自 CA を使う場合は CA バンドルをアプリから読み取れる場所に置き、`VCENTER_CA_BUNDLE` にそのパスを指定する。
3. 保存して接続テストを実行し、成功したら対象の収集結果を確認する。

アップグレード後に HTTP の登録が残っていた場合は、起動ログの `vCenter requires HTTPS in production` に対象 ID と有効・無効の状態が出る。HTTPS の登録で保存済みポートが 1〜65535 の整数でない場合は、`vCenter requires a valid port in production` が出る。アプリは起動を続けるので、設定を修正できる。小数のポートが DB に保存されていて管理画面の一覧を取得できない場合は、管理者権限で `PATCH /api/vcenters/{id}` に正しい `port`（例 `{"port": 443}`）を送る。`{id}` には起動ログの対象 ID を使う。

#### インベントリの関係の収集が進まない

インベントリの収集には、対象の VM、ホスト、クラスタ、データストア、ポートグループを参照できる vCenter の読み取り権限が必要。見える範囲は登録したアカウントの権限に従う。管理対象の件数が前回の成功から半分以下に減った場合は、`inventory_sync_states` の `last_warning` と `last_warning_at` を確認する。

`INVENTORY_SYNC_TIMEOUT_SECONDS` は vCenter ごとの観測の待ち時間と、収集用の HTTP ソケットのタイムアウトに使う。pyVmomi の制約により、`SmartConnect` の最初の API バージョン探索（`vimServiceVersions.xml` の取得）には HTTP タイムアウトが効かない。

探索で止まったデーモンスレッドは、呼び出しが戻るまで専用の収集枠を占める。ジョブは観測がタイムアウトすると次の vCenter に進む。前回の読み取りが残っている場合や専用スレッドに空きがない場合は、待たずにその回の失敗として記録する。イベントの取り込みは別のスレッドで動く。アプリの終了時は新しい読み取りの受付を閉じ、実行中のデーモンスレッドの完了を待たずに終了する。

vCenter を順に収集するため、1 回のジョブの読み取り待ち時間は最大で「有効な vCenter の数 × `INVENTORY_SYNC_TIMEOUT_SECONDS`」になり、DB 更新時間が加わる。前のジョブが収集間隔を超えて次回の実行時刻にも動いていると、APScheduler は次の実行を飛ばし、`maximum number of running instances reached` を WARNING で記録する。

### 3.4 DB障害（接続失敗/遅い/ディスク）

症状:

- API が `5xx` になりやすい
- ログにDB接続エラーが出る

確認:

- `DATABASE_URL` が正しいか（ホスト/ポート/ユーザー/DB名）
- SQLite ファイル運用なら、ディスク空きとファイル権限を確認する
- PostgreSQL 運用なら、接続数・ディスク・インデックス肥大の兆候を確認する
- 保持期間設定（イベント・メトリクス・通知履歴・ダイジェスト・インシデント・スナップショット）と実データ増加が整合しているか

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
- トークン上限や匿名化設定の影響を疑う場合は `docs/development/development.md` のチャット節を参照する

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
- インベントリ収集は `INVENTORY_SYNC_ENABLED`（既定 `true`）で切り替える。`INVENTORY_SYNC_INTERVAL_SECONDS`（既定 600 秒、下限 60 秒）で収集間隔を、`INVENTORY_SYNC_TIMEOUT_SECONDS`（既定 300 秒）で vCenter ごとの読み取りを待つ上限を設定する。
- APScheduler の `misfire_grace_time`: interval ジョブは各間隔の半分、cron ダイジェストは 3600 秒（`jobs/scheduler.py`）。イベントループ停止後の取りこぼし軽減用
- イベントとインベントリの保持期間は `EVENT_RETENTION_DAYS`（既定 7 日、下限 1 日）で設定する。メトリクスは `METRIC_RETENTION_DAYS` で設定する。`ALERT_HISTORY_RETENTION_DAYS`、`DIGEST_RETENTION_DAYS`、`INCIDENT_RETENTION_DAYS`、`INCIDENT_TIMELINE_SNAPSHOT_RETENTION_DAYS` は `0` でそれぞれの削除を無効にする。`INCIDENT_TIMELINE_SNAPSHOT_RESULT_RETENTION_DAYS` は保存結果だけの保持期間を設定し、`0` で保存結果の削除を無効にする。詳細は「インシデントの保持期間」と「スナップショットの保存結果の保持期間」を参照する。
  - タイムラインのスナップショットは、保存時点の結果（JSON）も残す。結果は、元のイベント・ログ・メトリクスの保持期間を過ぎても、`INCIDENT_TIMELINE_SNAPSHOT_RETENTION_DAYS`（既定 90 日）のあいだは残る。先に結果だけを消したいときは、`INCIDENT_TIMELINE_SNAPSHOT_RESULT_RETENTION_DAYS` を設定する。紐付いたスナップショットは行と保存結果の両方が削除の対象外になる。保存する結果は 1 件あたり最大 8 MiB で、超えると保存せず 413 を返す。
  - SQLite は、削除した行の領域をファイルサイズへ戻さない（空いた領域は次の書き込みで再利用される）。ファイルを縮めるには `VACUUM` が要る。
- ダイジェスト: `DIGEST_*`
- LLM とトレース: `LLM_*`, `LANGSMITH_*`
- ログ出力: `LOG_LEVEL`, `APP_LOG_FILE`, `UVICORN_LOG_FILE`
- 認証: `VEA_AUTH_ENABLED`（既定 `true`、本番では無効にできない）、`VEA_SESSION_*`、`VEA_LOGIN_*`、`VEA_BOOTSTRAP_ADMIN_PASSWORD` が残っていないこと（起動時に警告）
- プラグイン管理: `VEA_PLUGIN_MANAGEMENT_ENABLED`（既定 `false`）、`VEA_PLUGIN_ALLOW_INDEX_INSTALL`（既定 `false`）、`VEA_PLUGIN_DIR`
- 診断の設定: `VEA_DIAGNOSTICS_ENABLED`（既定 `false`、`VEA_AUTH_ENABLED=true` が必須）
- コレクタワーカーのログ: `VEA_COLLECTOR_WORKER_LOG_LEVEL`（未設定時は `LOG_LEVEL` を継承）
- SSH の接続先: `VEA_SSH_ALLOWED_PORTS`（許可するポートのカンマ区切り。既定は空で制限しない）。接続先の名前は、ホスト鍵の取得と収集の直前に名前解決し、ループバック・リンクローカル（メタデータ）・マルチキャスト・予約済み・未指定のアドレスに解決されると接続しない（RFC1918 は許可）
- 外へ接続して確かめる API の rate limit: `RATE_LIMIT_PROBE_PER_MINUTE`（既定 20 回/分、クライアントの IP ごと）。SSH のホスト鍵の取得・セットアップのアクション・ESXi の一覧・vCenter の接続テストが対象。診断のホスト鍵の取得と ESXi の一覧も同じ枠で数える
- チャット・プレビュー・インシデントタイムラインの集計と、調査資料の生成の上限
  - rate limit: `/api/chat` は `RATE_LIMIT_CHAT_PER_MINUTE`（既定 10 回/分）。`/api/chat/preview` と、タイムライン画面の `/api/incident-timeline/view` は、どちらもその 2 倍（既定 20 回/分）。いずれもクライアントの IP ごとで、超えると 429。3 つは別々に数える。スナップショットの手動保存（`POST /api/incident-timeline/snapshots/manual`）と、今の表示や保存した結果の出力（`POST /api/incident-timeline/export`、`GET /api/incident-timeline/snapshots/manual/{id}/export`）は `/view` と同じ枠で数える
  - 同時実行数: `CONTEXT_AGGREGATION_CONCURRENCY`（全体、既定 4）と `CONTEXT_AGGREGATION_CONCURRENCY_PER_USER`（利用者ごと、既定 1）。空きがなければ待たずに 503（`Retry-After` 付き）を返す。画面には「時間をおいて再度お試しください」と出る
  - イベントの集計行数: `CONTEXT_AGGREGATION_MAX_ROWS`（既定 100,000）。行数はおよそ「時間バケット数（最大 48 程度）× イベント種別数」で、超えると 422（vCenter を指定して絞り込むよう案内する）。メトリクスはカテゴリごとの上位 15 台を DB で選ぶので、この上限の対象ではない
  - vCenter を指定しないメトリクスの問い合わせ（チャット・プレビューの集計、ダッシュボードとダイジェストの上位ホスト、アラート評価の最新サンプル、タイムライン画面の超過区間）は、登録済みの vCenter の id を並べて絞る。SQLite が既存の索引 `ix_metric_samples_vcenter_metric_sampled_value` を vCenter ごとの範囲走査に使えるようにするため（統計が無いと指標の索引を選び、期間に関係なくその指標の全サンプルを読む）。新しい SQLite（3.51.0 以降で確認）は、統計が無いとこの索引ではなく UNIQUE 制約の自動索引 `sqlite_autoindex_metric_samples_1` を選ぶので、SQLite のときは `INDEXED BY` でこの索引に固定する。索引が無いと、問い合わせは遅くなるのではなく `no such index` のエラーになる（索引はマイグレーションで作られるので、マイグレーションを流していれば起きない。手で索引を消さないこと）。このコードのまま、索引を作るマイグレーション `f3a4b5c6d7e8` より前に downgrade すると、メトリクスの問い合わせが `no such index` のエラーになる。所要時間の目安（実測。SQLite、統計なし、200 ホスト・vCenter 2 つ・指標 8 種・5 分間隔・7 日で約 323 万行）は、チャットの集計（CPU とメモリ）が 6 時間 0.14 秒・24 時間 0.4 秒・7 日 6.6 秒（以前は期間に関係なく 22〜25 秒）、上位ホスト（24 時間）が 0.14 秒（以前は 11 秒）、アラート評価の最新サンプルが 1 ルールあたり 0.01 秒以下（以前は 11 秒）。PostgreSQL にはこの索引が無く、計画も所要時間も変わらない（同じデータでチャットの集計の 7 日が約 1.9 秒）
  - グラフ画面が使うメトリクスの一覧 API（`GET /api/metrics`）も、vCenter を指定しない（画面の既定「全て」）ときは、SQLite で上の 4 か所と同じく登録済みの vCenter の id を並べて絞る（Issue #324）。以前は期間に関係なくその指標の全サンプルを読んでいた。所要時間の目安（実測。SQLite、統計なし、200 ホスト・vCenter 2 つ・指標 8 種・5 分間隔・7 日で約 323 万行。期間ありは limit 10000、期間なしは limit 500。5 回の中央値）は、24 時間が件数 9.6 秒 → 0.27 秒・一覧 10.0 秒 → 0.35 秒、7 日が件数 9.8 秒 → 1.7 秒・一覧 11.1 秒 → 0.63 秒、期間なしが件数 0.25 秒 → 1.7 秒・一覧 10.5 秒 → 4.8 ms。期間なしの件数だけは遅くなる（細い `metric_key` だけの索引の代わりに、幅の広い索引で同じ行数を読むため）が、件数と一覧の合計では約 10.8 秒が約 1.75 秒になる。PostgreSQL では、この API に限って id を並べない（問い合わせは今までのまま）。PostgreSQL 16（同じ約 323 万行、ANALYZE 済み）で並べた場合と並べない場合を比べると、6 ケースのうち 5 ケースは計画も所要時間も変わらず、期間なしの件数だけが 9.9 ms から 125.8 ms に遅くなった（`metric_key` の索引だけでは数えられなくなり、表を読むため）。並べない場合の所要時間は、24 時間が件数 24 ms・一覧 17 ms、7 日が件数 127 ms・一覧 18 ms、期間なしが件数 10 ms・一覧 1.5 ms
  - タイムライン画面の API（`POST /api/incident-timeline/view`）は、同じ `CONTEXT_AGGREGATION_MAX_ROWS` を種別ごとの行数に当てる。対象は、`min_score` 以上のイベント、通知履歴、メトリクスの超過区間（区間の数。サンプル数ではない）、重大度が error 以上のログ。イベントか通知履歴が超えると、要求全体が 422 になる。エラーログかメトリクスの超過区間が超えたときは、422 にせず、その種別の行だけを一覧とハイライトから省き、応答の `omitted_sources` で伝える（ログの俯瞰の件数 `log_error` は返す。メトリクスの俯瞰 `metric_breach` は数えられないので 0 になる）。メトリクスの超過区間は CPU・メモリだけで、ディスク・ネットワークの指標は KB/s なので % の閾値を当てない。error 以上のログを期間で絞るために、式の索引 `ix_log_records_severity_norm_effective`（`lower(trim(severity))`, `effective_at`）と、vCenter を指定したとき用の `ix_log_records_vcenter_severity_norm_effective`（`vcenter_id`, `lower(trim(severity))`, `effective_at`）を使う
  - タイムライン画面のメトリクスの超過区間は、区間を作る前に、期間内の閾値以上のサンプルの数（CPU とメモリの合計。vCenter・対象で絞った後の数）を `TIMELINE_METRIC_BREACH_SAMPLE_LIMIT`（既定 40,000）+ 1 件で打ち切って数える。上限を超えたら区間を作らず、メトリクスだけを省いて返す（応答の `omitted_sources` は `{source: "metric", reason: "too_many_rows"}`。画面は「しきい値を上げるか、期間を短くするか、対象を絞ってください」と知らせる）。区間を作る時間は閾値以上のサンプルの数に比例するので、この上限が所要時間の上限になる。既定値は、SQLite で 7 日・200 ホストのとき、上限ぎりぎりでも 5 秒程度に収まる値。上げると省かれにくくなる代わりに、上限に近い要求ほど遅くなる（SQLite では 1 万件あたり 0.4 秒ほど延びる。7 日・200 ホストで 4.7 万件 2.5〜4.2 秒、13.8 万件 6.4〜7.6 秒）。PostgreSQL では上げても速い
  - 所要時間の目安（実測。200 ホスト、5 分間隔、指標 6 種、7 日で約 243 万行。メトリクスの処理 1 回の時間で、数え上げと区間の問い合わせの合計。幅は vCenter の指定の有無・対象の絞り込みと、ディスクのキャッシュの状態による）。SQLite は、vCenter・指標・時刻・値・moid・名前の索引 `ix_metric_samples_vcenter_metric_sampled_value` を使う（SQLite だけに作る）

    | 期間・データ | SQLite | PostgreSQL 16 |
    |---|---|---|
    | 1 時間 | 0.1 秒以下 | 0.1 秒以下 |
    | 24 時間 | 0.2〜1 秒 | 0.1〜0.3 秒 |
    | 7 日、各ホストが 1 日 1 時間だけ超過（閾値以上のサンプル 1.7 万件） | 1.2〜2.2 秒 | 0.5〜0.8 秒 |
    | 7 日、上限ぎりぎり（約 3.9 万件。超過が続く形と、1 サンプルおきに超過して区間が 2.4 万に分かれる形） | 1.6〜3.7 秒 | 0.6〜1.4 秒 |
    | 7 日、上限を超える（全ホストのメモリが 7 日間ずっと超過、約 42 万件）→ メトリクスを省く | 0.1 秒（対象で絞ると 0.6 秒） | 0.02〜0.4 秒（初回の対象の絞り込みで 1.3 秒） |

    上限を設ける前は、最後の行のデータで区間を作るのに SQLite で 27〜35 秒、PostgreSQL で 3.4 秒かかった。ホストの数が多い、または超過が多い環境では PostgreSQL が向く（同じ上限ぎりぎりのデータで、SQLite の 1.6〜3.7 秒に対して 0.6〜1.4 秒）。PostgreSQL で 7 日の要求のとき、超過が少ないと数え上げが表を順に読む（約 243 万行で 0.2〜0.5 秒。表の大きさに比例する）。SQLite の値は、統計（`ANALYZE`）の有無で大きく変わらない（アプリは `ANALYZE` を実行しない。統計が無くても、上のとおり `INDEXED BY` で索引を固定するので、新しい SQLite でも同じ索引を使う）。メモリの使用率が常に閾値を超える環境では、画面の条件のメモリの閾値（`metric_threshold_memory_pct`、既定 85%）を実情に合わせて上げると、省かれずに開ける。PostgreSQL では、区間の問い合わせの前にトランザクションの中だけ JIT を切る（行数の見積もりが大きく外れ、JIT のコンパイルが実行より長くかかるため）
  - 利用者ごとの同時実行数は、チャット・プレビュー・インシデントタイムラインで共有する。同じ利用者が別のタブでタイムラインを生成している間にチャットを送ると、片方が 503 になる。困る場合は `CONTEXT_AGGREGATION_CONCURRENCY_PER_USER` を 2 にする
  - 集計の要求を途中で取り消すと枠はすぐ返るが、SQLite では実行中のクエリが最後まで走る。取り消しを繰り返すと、一時的に上限より多くの集計が DB で走ることがある（PostgreSQL ではクエリも取り消される）
  - 調査資料の生成も集計と同じ同時実行の枠を使う。生成の途中で要求を取り消しても、スレッドでの生成が終わってから枠を返す。出力に成功すると、出典・形式・バイト数をアプリの info ログに残す
  - 上限はどれもプロセスごとに数える。複数のワーカーで動かすと、全体の上限は「上限 × ワーカー数」になる。リバースプロキシの後ろでは rate limit のキー（クライアントの IP）が全員同じになり、1 つの枠を共有する。認証を無効にしている場合、同時実行数は全員が 1 人の利用者として数えられる
- コレクタワーカーの環境変数: `VEA_PLUGIN_WORKER_ENV_PASSTHROUGH`（プラグインが独自の環境変数を読むときだけ）、`VEA_PROCESS_NON_DUMPABLE`（既定 `true`、Linux のみ）。詳細は `docs/operations/collector-plugins.md` の「脅威モデル」

## 4.1 プラグイン管理を有効化する場合

`VEA_PLUGIN_MANAGEMENT_ENABLED=true` にすると、`/api/plugins` の変更系 API（設定変更・リロード・
インストール・アンインストール）が開きます。**これは実質的に任意コード実行を許す操作です。**
これらの API は admin ロールだけが呼べます。有効化する場合は次を必ず満たしてください。

- admin ロールは信頼できる利用者だけに付与する（`vcenter-event-assistant-admin list-users` で定期的に確認する）
- `VEA_PLUGIN_ALLOW_INDEX_INSTALL` は原則 `false` のままにし、アップロード経路のみを使う
  （`true` にすると実行時に外部インデックスから取得するため、サプライチェーンリスクが増える）
- インデックスは `VEA_PLUGIN_INDEX_URL` で指定する。`UV_INDEX_URL` などの uv の環境変数はインストーラに渡さない。URL かプロキシの環境変数に資格情報を含めると、wheel だけを入れる（`--no-build`）。そのときアップロードした sdist は、インデックスを使わずに入れる（依存は解決されない）
- 本番ではアプリを `exec` で起動する（`uv run` を使わず `exec .venv/bin/vcenter-event-assistant` で起動する。`exec` を付けずに対話シェルから実行すると、シェルが親として残る。Docker イメージはそうなっている）。同じユーザーの親プロセスが秘密の環境変数（資格情報を含むプロキシやインデックスの URL も）を持ったまま残ると、プラグインから読める。動き続けるプロセス管理ツールは exec では解決しないので、別のユーザー（root の systemd など）で動かすか、秘密を持たせない。この警告は変数の名前で判定する目安で、すべての秘密を見つけられるわけではない（判定の条件は [コレクタプラグイン](collector-plugins.md) の「脅威モデル」）。起動時に `the parent process ... keeps secret environment variables` の WARNING が出たら起動方法を見直す
- 公式 Compose はプラグイン系の処理を別 UID で動かす。既存 Compose の更新と、Docker なしの Linux で同じ分離を有効にする手順は [脅威モデル](collector-plugins.md#脅威モデル) を参照する。分離を設定していない単体起動では、インストール中のインデックスやプロキシの資格情報が同じ UID のワーカーから見える
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

**完全な情報はコレクタワーカープロセスの stderr にあります。** 公式 Compose では
`docker compose logs plugin-worker` で確認できます。分離を設定していない単体起動では
アプリのログに含まれます。行頭が
`[collector-worker <pid>]` になっているものがワーカー由来です。

詳細を出したいときは `VEA_COLLECTOR_WORKER_LOG_LEVEL=DEBUG` にします。アプリ全体の
`LOG_LEVEL` は変えずに、外部プラグインのログだけを詳細化できます。

よくある失敗:

| `error_message` | 意味 | 対処 |
|---|---|---|
| `ModuleNotFoundError: No module named '...'` | プラグインの依存が入っていない | アップロード導入は `--no-index --no-deps` で実行されるため依存が解決されない。インデックス経由での導入を許可するか、依存を同梱したパッケージを作り直す |
| `load failed: ...` | entry point の読み込みに失敗 | ワーカーの stderr にトレースバックが出ている |
| `TimeoutError: collector execution failed` | `timeout_seconds` 超過でワーカーを kill | 実行間隔とタイムアウトを見直す。ワーカーは次回実行で作り直される |
| `BatchValidationError: ...` | バッチ検証で拒否。違反した規則がそのまま表示される | プラグイン側の修正が必要。条件の一覧は `docs/development/collector-plugin-authoring.md` の「バッチが拒否される条件」 |

## 4.2 認証を導入したバージョンへの更新

0.2.0 から、認証が既定で有効になります（`VEA_AUTH_ENABLED=true`）。項目 6〜9 も 0.2.0 の変更です（変更の一覧は [CHANGELOG](../../CHANGELOG.md)）。更新前に次を準備してください。

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
6. アラートメールの STARTTLS で、SMTP サーバの証明書を検証するようになりました。自己署名や社内 CA の証明書の SMTP では、`SMTP_CA_BUNDLE` に CA バンドルを指定してください（検証用の環境なら `SMTP_TLS_VERIFY=false`）。指定しないとメールが届かなくなります。指定したファイルがないと起動しないので、Docker ではファイルをコンテナにマウントし、コンテナの中のパスを指定してください（詳細は「E) SMTP/メール通知」）
7. プラグインのワーカーには、許可した環境変数しか渡さなくなりました。プラグインが独自の環境変数（機密値など）を読む場合は、その名前を `VEA_PLUGIN_WORKER_ENV_PASSTHROUGH` にカンマ区切りで書いてください。インデックスからのインストールでは、`UV_INDEX_URL` などの uv の環境変数は効かなくなったので、`VEA_PLUGIN_INDEX_URL` で指定してください（詳細は `docs/operations/collector-plugins.md` の「脅威モデル」と「動的インストール」）
8. Docker イメージで、アプリのコードと `.venv`（`/app`）を root の所有にし、実行ユーザー（`appuser`）からは書き込めなくしました（プラグインに本体を書き換えさせないため）。DB とプラグインの既定の置き場所（`/app/data`）は `/data` へのシンボリックリンクになり、実体は `/data` に置かれます。compose のテンプレートで動かしている場合も、`docker run` で `/app/data` にボリュームをマウントしている場合も、そのまま動きます（マウントはリンクをたどって `/data` に入ります）。`/app` の下に他のファイルを書き込む構成にしている場合は、`/data` に移してください
9. SSH の接続先（リモートログの収集）は、ホスト鍵の取得と収集の直前に名前解決し、ループバック・リンクローカル（メタデータ）・マルチキャスト・予約済み・未指定のアドレスに解決される名前には接続しなくなりました（RFC1918 のプライベートな IP は今までどおり接続できます）。また、SSH のホスト鍵の取得・セットアップのアクション・ESXi の一覧・vCenter の接続テストに rate limit（`RATE_LIMIT_PROBE_PER_MINUTE`、既定 20 回/分）がかかります。同梱のリモートログのプラグインは 0.3.0（plugin-api 1.5 以降が必要）になりました。別にインストールしている場合は、両方を更新してください

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

## 4.3 診断の設定を有効化する場合

`VEA_DIAGNOSTICS_ENABLED=true` にすると、admin が `/api/diagnostics` で診断用の SSH 鍵と接続先、ESXi・vCenter の対象、追加コマンドの雛形を管理できます。認証を無効にする設定と併用すると、アプリは起動を拒否します。機能が無効のとき、診断設定の API は 404 を返します。

診断とログ収集には別々の SSH アカウントと鍵を用意してください。移行前の SSH 鍵と接続先はログ収集用として引き継ぎます。診断用の SSH 鍵と接続先は、用途の列を持たない版へダウングレードすると削除されます。診断用の秘密鍵の保存にも `VEA_SECRET_KEY` が必要です。追加コマンドが読み取り専用かどうかは本体では確かめません。

設定の変更は `diagnostics.command.*`、`diagnostics.target.*`、`diagnostics.ssh.*` の監査ログに残ります。監査ロガーは `LOG_LEVEL` にかかわらず INFO で記録し、SSH 秘密鍵は記録しません。

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

### 5.4 索引を足すマイグレーションの所要時間

アプリの更新で索引を足すマイグレーションが入ると、起動時の自動マイグレーション（`VEA_DB_AUTO_MIGRATE`）が索引を作り終えるまで、アプリは起動しない。索引の作成中は、その表への書き込み（収集の取り込み）も止まる。表が大きい環境では、更新の時間帯を収集の少ない時間に寄せる。複数のプロセスが同時に起動したときは、マイグレーションの完了をロックで待つ（`VEA_DB_MIGRATION_LOCK_TIMEOUT_SECS`、既定 300 秒）。索引の作成がこれより長くかかる環境では、値を延ばすか、1 つのプロセスで先にマイグレーションを済ませる。

実測の目安（開発機。ディスクや同時の負荷で変わる）:

- `e2f3a4b5c6d7`（`log_records` の式の索引）: PostgreSQL 16 で 300 万行 3.3 秒、605 万行 5.0 秒
- `f3a4b5c6d7e8`（タイムライン用の索引 2 つ）:
  - `log_records` の vCenter 付きの式の索引: PostgreSQL 16 で 605 万行 5.9 秒、SQLite で 30 万行 2.9 秒
  - `metric_samples` の vCenter・指標・時刻・値・moid・名前の索引（SQLite だけ）: SQLite で 243 万行 25〜34 秒

`b1c2d3e4f5a6`（ログの型の列・索引と台帳）を開発機で計測した。SQLite は 100 の出どころを持つログを使用した。PostgreSQL 16 は Docker 上で、605 万行（`log_records` 4.2 GB）を使用した。

| 処理 | SQLite（30 万行） | PostgreSQL 16（605 万行） |
| --- | ---: | --- |
| 索引 `(vcenter_id, pattern_key, effective_at)` の作成 | 0.32 秒 | 9.5 秒 |
| 出どころの集計（`DISTINCT`） | 0.11 秒（開始行の作成を含む） | 2.8 秒 |
| 移行全体 | 0.46 秒 | 15.1 秒 |

移行全体の時間にバックアップは含まない。

SQLite での埋め戻しは 50,000 行で 14.53 秒、キーが付いた 5,000 行の追いつきは 0.08 秒だった。
伏せ方だけを 1 万行に適用する時間は 0.56 秒だった。
PostgreSQL 16 での埋め戻しは 1 回 50,000 行で 20.9〜21.8 秒だった。605 万行では 121 回、5 分おきの実行で約 10 時間かかる。
追いつきは、キーが付いた 5,000 行で 0.03 秒、新しい行が無い場合は 0.01 秒だった。

データを書き換えるマイグレーションも、終わるまでアプリは起動しない:

- `b5c6d7e8f9a0`（指標名 `host.disk.usage_pct` を `host.disk.usage_kbps` に付け替える）: `metric_samples` のうち、この指標の行だけを UPDATE する。所要時間は計測していない。行数は `SELECT count(*) FROM metric_samples WHERE metric_key = 'host.disk.usage_pct'` で確かめられる

### 5.5 ロールバック手順（最小）

1. `.env` を変更前の値に戻す
2. アプリケーションプロセスを再起動する
3. `GET /health` を再確認する
4. ジョブログの異常が収束したことを確認する

ログの型を付ける前のコードが稼働を続けている間に取り込んだログには、型のキーが入らない。
移行済みの DB で新しいコードを稼働させると、定期ジョブが追いついて型を付ける。
旧版のプロセスを起動し直す場合、そのコードが移行後のリビジョンを認識できなければ起動時の確認で止まる。
型の移行を直前の版（`a0b1c2d3e4f5`）までダウングレードすると、ログ本文は残り、型のキーと台帳は消える。
再度アップグレードしたときは、保持されているログから台帳を作り直す。

## 6. 関連ドキュメント

- バックエンド全体入口: `docs/development/backend.md`
- システム全体像: `docs/features/architecture.md`
- 開発者向け詳細: `docs/development/development.md`（チャット/LLM の挙動や環境変数の詳細）
