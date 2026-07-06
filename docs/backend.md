# バックエンドガイド

本ドキュメントは、vCenter Event Assistant のバックエンドを **最短で把握して運用・改修に着手することを目的** としています。対象読者は、開発者と運用担当者の両方です。

## 0. この文書の位置づけ

- [`docs/backend.md`](backend.md): バックエンド全体の把握（本ドキュメント）
- [`docs/development.md`](development.md): 開発者向け手順（テスト、ツール、LLM詳細など）
- [`docs/backend-operations.md`](backend-operations.md): 運用（監視、障害対応、変更管理）
- [`docs/backend-internals.md`](backend-internals.md): 開発者向けの詳細解説（機能を追加・変更するためのガイドなど）

## 1. 役割と構成

バックエンドは FastAPI を中心に、次を担います。

- `/api` の HTTP API 提供
- vCenter からのイベント/メトリクス収集（pyVmomi）
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
  フィルタ付きイベント一覧（`total` を含む）。利用者向けの説明は [user-guides/events.md](user-guides/events.md)。
- `PATCH /api/events/{event_id}`  
  イベントへのユーザーコメント（運用メモ）更新（利用者向けは上記 events.md）。
- `GET /api/events/event-types`  
  イベント種別一覧。
- `GET /api/events/rate-series`  
  指定イベント種別の時系列件数。
- `GET /api/metrics/keys`  
  メトリクスキー一覧。
- `GET /api/metrics`  
  メトリクス系列（`total` と `X-Total-Count` を返却）。利用者向けの説明は [user-guides/graph.md](user-guides/graph.md)。
- `GET /api/dashboard/summary` — 利用者向けの説明は [user-guides/summary.md](user-guides/summary.md)  
  直近24hの集約サマリー。

### 2.4 ルール・ガイド・アラート

- `GET/POST/PATCH/DELETE /api/event-score-rules`
- `POST /api/event-score-rules/import`
- `GET/POST/PATCH/DELETE /api/event-type-guides`
- `POST /api/event-type-guides/import`
- `GET/POST/PATCH/DELETE /api/alerts/rules`
- `GET /api/alerts/history`

アラートルールは `alert_level`（`critical` / `error` / `warning`）を持ち、メール通知の件名・本文および `alert_history` の各行に、通知時点のレベルが記録される。既存 DB はマイグレーションで `warning` を既定とする。イベント行の `severity`（VMware 由来）とは別の運用重大度である。
`PATCH /api/alerts/rules/{id}` では `name` の重複更新は `409` を返し、`config` は部分更新ではなく全置換として扱う。

#### 定期アラート評価（トラブルシュート）

利用者向けの説明（画面操作・メールの読み方・FAQ）は [user-guides/alerts.md](user-guides/alerts.md) を参照する。要注目スコアとスコアルールの設定は [user-guides/score-rules.md](user-guides/score-rules.md) を参照する。

- バックグラウンドジョブ `evaluate_alerts` は `ALERT_EVAL_INTERVAL_SECONDS`（既定 60 秒）ごとに動く。ログの `executed successfully` は **例外がなかったこと** を示し、必ずしも発火したとは限らない。
- **有効な AlertRule が 1 件以上**必要（設定 → アラート、有効チェック ON）。
- `metric_threshold` ルールの `config.metric_key` は、DB に保存されるキーと **完全一致** させる（CPU 利用率の例: `host.cpu.usage_pct`）。`GET /api/metrics/keys` またはグラフタブのキー一覧を参照する。UI 旧既定の `cpu.usage.average` ではサンプルにヒットしない。
- `metric_threshold` の `AlertState.context_key` は **`{vcenter_id}:{entity_moid}`** 形式（vCenter 間の MoRef 衝突を避ける）。鮮度上限（`METRIC_STALENESS_WINDOW_SECONDS`、未設定時は `PERF_SAMPLE_INTERVAL_SECONDS * 3`）を超えたサンプルは評価対象外。`firing` 中に鮮度切れすると **`stale`** へ遷移し、初回のみ通知する。
- 発火の確認は **通知履歴**（`GET /api/alerts/history`、画面の「通知履歴」タブ）。`_notify` が呼ばれると履歴行が増える。メールは `SMTP_HOST` と `ALERT_EMAIL_TO` が設定されているときのみ送信される（未設定時は warning ログのみで履歴は残る）。
- 評価完了時に INFO ログ `alert evaluation complete rules_enabled=N firings=M resolutions=R` が出る。`firings=0` が続く場合は閾値・キー・収集データを見直す。
- 既に `firing` 状態の metric ルールは、条件が続いても **新規通知は出ない**（エンティティごとの状態更新のみ）。回復後に再度閾値超えで firing する。
- **`event_score` ルール**（利用者向けの挙動の正本は [user-guides/alerts.md](user-guides/alerts.md)。本節は実装・トラブルシュート用の補足）
  - 判定はイベント一覧と同じ DB 列 `notable_score >= config.threshold` かつ `occurred_at >= now - ALERT_EVENT_EVAL_LOOKBACK_HOURS`（**全ルール共通**。ルール `config` に lookback はない）。
  - ウィンドウは `.env` の `ALERT_EVENT_EVAL_LOOKBACK_HOURS`（1〜168、既定 1）。**アプリ再起動**で反映。`ALERT_SNAPSHOT_LOOKBACK_HOURS`（スナップショット用・既定 2）とは別。
  - `config` は `threshold`（必須・0〜100）と `cooldown_minutes`（任意、既定 10）。JSON インポートで `threshold` が文字列でも評価側で数値化する。レガシー `min_notable_score` は `threshold` として読む。
  - 状態は **`event_type`（イベント種別）ごと** の `AlertState` を持ち、通知の Resource / `context_key` は **イベント種別名** である。`cooldown_minutes` は **同一種別へのメール再送の最短間隔（再通知間隔）のみ** に用いる。`last_notified_at` 等と組み合わせ、**間隔未満の再送を抑止** する。
  - **沈黙やウィンドウの切れ目だけで `resolved`（自動回復）にはしない**。調査完了後の手動解消は **今後の機能追加で対応予定**。
  - ログに `Error evaluating rule` や `invalid config` が出ていないか確認する。

### 2.5 収集・ダイジェスト・チャット

利用者向けの説明（本文の読み方・画面操作・FAQ）は [user-guides/digests.md](user-guides/digests.md) を参照する。

- `POST /api/ingest/run`  
  有効な全 vCenter に対して手動インジェストを実行。
- `GET /api/digests`
- `GET /api/digests/{digest_id}`
- `POST /api/digests/run`  
  ダイジェストを手動生成。
- `POST /api/chat`
- `POST /api/chat/preview`  
  期間コンテキスト付きチャットとプレビュー。利用者向けの説明は [user-guides/chat.md](user-guides/chat.md) を参照する。

## 3. 設定の要点（環境変数）

設定は `settings.py` の `Settings` に集約されています。主な運用項目は次のとおりです。

- DB:
  - `DATABASE_URL`
- 収集・保持:
  - `EVENT_POLL_INTERVAL_SECONDS`
  - `PERF_SAMPLE_INTERVAL_SECONDS`
  - `EVENT_RETENTION_DAYS`
  - `METRIC_RETENTION_DAYS`
- ジョブ:
  - `SCHEDULER_ENABLED`
  - `ALERT_EVAL_INTERVAL_SECONDS`
  - `DIGEST_DAILY_*`, `DIGEST_WEEKLY_*`, `DIGEST_MONTHLY_*`
  - **非推奨（v0.3.0 削除予定）**: `DIGEST_SCHEDULER_ENABLED`, `DIGEST_CRON` — 日次ダイジェスト向けレガシー名。実効値は `effective_digest_daily_*` で新設定と合成される。移行先は `DIGEST_DAILY_ENABLED` / `DIGEST_DAILY_CRON`。レガシーが有効なとき起動ログに WARNING が出る。
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

フロント開発を併用する場合は、別端末で `frontend` の Vite 開発サーバーを起動し、`/api` はプロキシ経由でバックエンドへ接続します。詳細は `docs/getting-started.md` を参照してください。

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

## 7. 関連ドキュメント

- 全体アーキテクチャ: `docs/architecture.md`
- 利用開始: `docs/getting-started.md`
- 内部実装ガイド（API層中心）: `docs/backend-internals.md`
- 開発者向けメモ: `docs/development.md`
- チャット機能（利用者向け）: `user-guides/chat.md` — 概要・補助: `docs/chat.md`
- 現状実装の整理: `docs/plans/2026-03-21-vcenter-event-assistant-as-built.md`
