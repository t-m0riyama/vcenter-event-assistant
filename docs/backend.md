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
  フィルタ付きイベント一覧（`total` を含む）。
- `GET /api/events/event-types`  
  イベント種別一覧。
- `GET /api/events/rate-series`  
  指定イベント種別の時系列件数。
- `PATCH /api/events/{event_id}`  
  イベントへのユーザーコメント更新。
- `GET /api/metrics/keys`  
  メトリクスキー一覧。
- `GET /api/metrics`  
  メトリクス系列（`total` と `X-Total-Count` を返却）。
- `GET /api/dashboard/summary`  
  直近24hの集約サマリー。

### 2.4 ルール・ガイド・アラート

- `GET/POST/PATCH/DELETE /api/event-score-rules`
- `POST /api/event-score-rules/import`
- `GET/POST/PATCH/DELETE /api/event-type-guides`
- `POST /api/event-type-guides/import`
- `GET/POST/PATCH/DELETE /api/alerts/rules`
- `GET /api/alerts/history`

### 2.5 収集・ダイジェスト・チャット

- `POST /api/ingest/run`  
  有効な全 vCenter に対して手動インジェストを実行。
- `GET /api/digests`
- `GET /api/digests/{digest_id}`
- `POST /api/digests/run`  
  ダイジェストを手動生成。
- `POST /api/chat`
- `POST /api/chat/preview`  
  期間コンテキスト付きチャットとプレビュー。

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
- チャット機能: `docs/chat.md`
- 現状実装の整理: `docs/plans/2026-03-21-vcenter-event-assistant-as-built.md`
