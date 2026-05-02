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

- アプリの保持設定（`EVENT_RETENTION_DAYS`, `METRIC_RETENTION_DAYS`）と、DBディスクの増加傾向が矛盾していないかを週次で確認する

#### E) SMTP/メール通知（配信経路）

設定（環境変数名の例）:

- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`
- `ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO`

監視の考え方:

- メール送信は `src/vcenter_event_assistant/services/notification/email_channel.py` が担当する
- `SMTP_HOST` 未設定、または `ALERT_EMAIL_TO` 未設定の場合は送信をスキップし、警告ログが出る
  - `SMTP_HOST is not set. Skipping email notification.`
  - `ALERT_EMAIL_TO is not set. Skipping email notification.`
- 送信失敗時はエラーログが出る
  - `Failed to send email notification: ...`

運用上の注意:

- メール未設定でもアプリは動くため、「アラートをメールで必ず届けたい」運用では、上記警告が継続しないことを監視対象に含める

## 3. 障害対応 Runbook

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
- `EVENT_RETENTION_DAYS` / `METRIC_RETENTION_DAYS` と実データ増加が整合しているか

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
  - LLM 呼び出しに失敗した場合、`status` は `ok` のまま `error_message` に省略理由が入ることがある

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

- ログに次が出ていないか（`src/vcenter_event_assistant/services/notification/email_channel.py`）
  - `SMTP_HOST is not set. Skipping email notification.`
  - `ALERT_EMAIL_TO is not set. Skipping email notification.`
  - `Failed to send email notification: ...`
- `alert evaluation job failed` が出ていないか（`src/vcenter_event_assistant/jobs/scheduler.py`）

対処の例:

- SMTP 設定を正す
- 認証情報・TLS設定・宛先を正す

## 4. 運用設定チェックリスト

日次/週次点検で、少なくとも次を確認します。

- DB: `DATABASE_URL`
- スケジューラ有効化: `SCHEDULER_ENABLED`
- 保持期間: `EVENT_RETENTION_DAYS`, `METRIC_RETENTION_DAYS`
- ダイジェスト: `DIGEST_*`
- LLM とトレース: `LLM_*`, `LANGSMITH_*`
- ログ出力: `LOG_LEVEL`, `APP_LOG_FILE`, `UVICORN_LOG_FILE`

## 5. 変更管理（実務向け最小）

### 5.1 変更タイプ

- 設定値変更（`.env`）
- スケジューラ関連変更（周期・有効/無効）
- LLM 関連変更（プロバイダ、キー、モデル、匿名化）

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
