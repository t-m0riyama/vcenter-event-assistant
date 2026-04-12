# 機能一覧

本書は **vCenter Event Assistant** の機能を **フロントエンド・バックエンド・LLM連携別**に一覧化し、LLM利用の有無を明確にしたドキュメントである。

---

## 1. フロントエンド機能

### 📱 UI構成（React タブインターフェース）

vCenter Event Assistant のフロントエンドは、以下の **6つのタブ**で構成される SPA である。

| タブ ID | 画面名 | 主要機能 | LLM連携 | 技術 |
|--------|-------|--------|--------|------|
| `summary` | **📊 概要** | vCenter数、イベント/要注意件数、要注意TOP、イベント種別TOP、高CPU/メモリホストTOP | ❌ | ダッシュボード・リアルタイム集計 |
| `events` | **📋 イベント** | イベント一覧・フィルタ・ページネーション、CSV出力、イベント種別ガイド表示、ユーザーコメント編集 | ❌ | 時系列検索・フルテキスト検索 |
| `metrics` | **📈 グラフ** | CPU/メモリ等メトリクスの時系列グラフ、vCenter・メトリクス・期間選択、ズーム・凡例操作 | ❌ | Recharts、24h/7日/30日プリセット |
| `digests` | **📄 ダイジェスト** | ダイジェスト一覧・検索、Markdown表示、手動実行（日次/週次/月次）、ダウンロード | ✅ **オプション** | LLM要約は設定で有効/無効 |
| `chat` | **💬 チャット** | LLM との期間別対話、メトリクス・イベント・コンテキスト含める、会話履歴（最大200件） | ✅ **必須** | LangChain / Copilot CLI対応 |
| `settings` | **⚙️ 設定** | テーマ・タイムゾーン、vCenter登録、ガイド・ルール・プロンプト管理 | ❌ | CRUD + JSON操作 |

### ⚙️ 設定タブ（Sub-tabs）

`settings` タブは以下の **5つのサブタブ**を含む。

| サブタブ | 機能 | 操作 | LLM連携 |
|--------|------|------|--------|
| **一般** | テーマ（ライト/ダーク）、タイムゾーン、チャット最大保持件数 | 選択・スライダー | ❌ |
| **vCenter管理** | vCenter登録・更新・削除、接続テスト（pyVmomi） | CRUD + テスト | ❌ |
| **イベント種別ガイド** | イベント種別ごとの説明・原因・対処、JSON インポート/エクスポート | CRUD + JSON操作 | ❌ |
| **スコアルール** | イベント種別ごとのスコア調整ルール、JSON インポート/エクスポート | CRUD + JSON操作 | ❌ |
| **チャットプロンプト** | チャット用サンプルプロンプトスニペット管理 | CRUD | ❌ |

### 🛠️ フロントエンド技術構成

| 領域 | 技術・ライブラリ | 用途 |
|-----|-----------------|------|
| **ビルド** | Vite | 開発・本番ビルド、HMR |
| **言語** | TypeScript | 型安全なコンポーネント開発 |
| **UI フレームワーク** | React | SPA 構築 |
| **グラフ表示** | Recharts | メトリクス時系列グラフ |
| **ブラウザ保存** | localStorage | テーマ・タイムゾーン・チャット履歴 |
| **通信** | Fetch API | `/api/*` エンドポイント呼び出し |
| **E2E テスト** | Playwright | 画面キャプチャ・自動テスト |

---

## 2. バックエンド API 機能

### 🔌 API エンドポイント一覧（FastAPI）

vCenter Event Assistant は以下の **11個のエンドポイントグループ** と **6個の定期実行ジョブ**で構成される。

#### イベント管理 (`/api/events`)

| メソッド | エンドポイント | 説明 | パラメータ例 | LLM連携 | DB操作 |
|--------|------------|------|----------|---------|--------|
| `GET` | `/events/event-types` | イベント種別一覧（上位N件） | `vcenter_id`, `limit` | ❌ | SELECT |
| `GET` | `/events/rate-series` | イベント発生レート時系列（バケット集計） | `event_type`, `from`, `to`, `bucket_seconds` | ❌ | SELECT |
| `GET` | `/events` | イベント一覧（フィルタ・ページネーション） | `min_score`, `event_type_contains`, `severity`, `message_contains` | ❌ | SELECT |
| `PATCH` | `/events/{event_id}` | ユーザーコメント更新 | `user_comment` | ❌ | UPDATE |

#### ダッシュボード (`/api/dashboard`)

| メソッド | エンドポイント | 説明 | 出力内容 | LLM連携 | DB操作 |
|--------|------------|------|--------|---------|--------|
| `GET` | `/dashboard/summary` | 概要サマリー（24h集計） | vCenter数、イベント/要注意件数、TOP要注意イベント、TOPイベント種別、高負荷ホスト | ❌ | SELECT |

#### メトリクス (`/api/metrics`)

| メソッド | エンドポイント | 説明 | パラメータ例 | LLM連携 | データ元 |
|--------|------------|------|----------|---------|---------|
| `GET` | `/metrics/keys` | 利用可能メトリクスキー一覧 | `vcenter_id` | ❌ | DB SELECT |
| `GET` | `/metrics` | メトリクス時系列データ | `metric_key`, `from`, `to`, `entity_moid` | ❌ | DB SELECT |

#### ダイジェスト (`/api/digests`)

| メソッド | エンドポイント | 説明 | 処理内容 | LLM連携 | DB操作 |
|--------|------------|------|--------|---------|--------|
| `GET` | `/digests` | ダイジェスト一覧 | ページネーション | ❌ | SELECT |
| `GET` | `/digests/{digest_id}` | ダイジェスト詳細（Markdown本文） | 取得 | ❌ | SELECT |
| `POST` | `/digests/run` | ダイジェスト手動実行 | 日次/週次/月次の集計・テンプレート・LLM要約 | ✅ **オプション** | INSERT + LLM呼び出し |

#### チャット (`/api/chat`)

| メソッド | エンドポイント | 説明 | 入力 | LLM連携 | 処理 |
|--------|------------|------|------|---------|------|
| `POST` | `/chat` | LLM期間別チャット | `from_time`, `to_time`, `messages`, `include_period_metrics_*` | ✅ **必須** | イベント/メトリクス集計 → LLM送信 → 応答 |

#### vCenter管理 (`/api/vcenters`)

| メソッド | エンドポイント | 説明 | 処理 | LLM連携 | DB操作 |
|--------|------------|------|------|---------|--------|
| `GET` | `/vcenters` | vCenter一覧 | 取得 | ❌ | SELECT |
| `POST` | `/vcenters` | vCenter登録 | 登録（暗号化保存） | ❌ | INSERT |
| `GET` | `/vcenters/{vcenter_id}` | vCenter詳細 | 取得 | ❌ | SELECT |
| `PATCH` | `/vcenters/{vcenter_id}` | vCenter更新 | 更新 | ❌ | UPDATE |
| `DELETE` | `/vcenters/{vcenter_id}` | vCenter削除 | 関連イベント・メトリクスも削除 | ❌ | DELETE (CASCADE) |
| `GET` | `/vcenters/{vcenter_id}/test` | 接続テスト | pyVmomi で vCenter 接続確認 | ❌ | pyVmomi API呼び出し |

#### イベント種別ガイド (`/api/event-type-guides`)

| メソッド | エンドポイント | 説明 | 処理 | LLM連携 | DB操作 |
|--------|------------|------|------|---------|--------|
| `GET` | `/event-type-guides` | ガイド一覧 | 取得 | ❌ | SELECT |
| `POST` | `/event-type-guides` | ガイド作成 | 作成 | ❌ | INSERT |
| `PATCH` | `/event-type-guides/{guide_id}` | ガイド更新 | 更新 | ❌ | UPDATE |
| `DELETE` | `/event-type-guides/{guide_id}` | ガイド削除 | 削除 | ❌ | DELETE |
| `POST` | `/event-type-guides/import` | JSON一括インポート | JSON解析・DB全置換 | ❌ | DELETE/INSERT |

#### イベント種別スコアルール (`/api/event-score-rules`)

| メソッド | エンドポイント | 説明 | 処理 | LLM連携 | DB操作 |
|--------|------------|------|------|---------|--------|
| `GET` | `/event-score-rules` | ルール一覧 | 取得 | ❌ | SELECT |
| `POST` | `/event-score-rules` | ルール作成 | 作成 → 関連イベントスコア再計算 | ❌ | INSERT + スコア更新 |
| `PATCH` | `/event-score-rules/{rule_id}` | ルール更新 | 更新 → 関連イベントスコア再計算 | ❌ | UPDATE + スコア更新 |
| `DELETE` | `/event-score-rules/{rule_id}` | ルール削除 | 削除 → 関連イベントスコア再計算 | ❌ | DELETE + スコア更新 |
| `POST` | `/event-score-rules/import` | JSON一括インポート | JSON解析・DB全置換 → 全イベントスコア再計算 | ❌ | DELETE/INSERT + 全スコア更新 |

#### システム (`/api/config`, `/api/health`)

| メソッド | エンドポイント | 説明 | 返却内容 | LLM連携 | DB操作 |
|--------|------------|------|--------|---------|--------|
| `GET` | `/config` | アプリ設定情報 | `event_retention_days`, `metric_retention_days` | ❌ | 設定読み込み |
| `GET` | `/health` | ヘルスチェック | `{"status": "ok"}` | ❌ | 接続確認 |

### 🔄 ジョブ・スケジューリング（定期実行、APScheduler）

| Job ID | トリガー | 処理内容 | 頻度 | LLM連携 | 入力元 |
|--------|--------|--------|------|---------|--------|
| `poll_events` | **Interval** | vCenter からイベント定期ポーリング → DB挿入・スコア計算 | `event_poll_interval_seconds` (既定60秒) | ❌ | **pyVmomi** (vCenter API) |
| `poll_perf` | **Interval** | vCenter からホストメトリクス定期サンプリング（CPU/メモリ%） → DB挿入 | `perf_sample_interval_seconds` (既定300秒) | ❌ | **pyVmomi** (`quickStats`) |
| `purge_metrics` | **Interval** | 期限切れイベント・メトリクス削除 | 6時間ごと | ❌ | DB |
| `digest_daily` | **Cron** | 日次ダイジェスト生成（テンプレート + オプション: LLM要約） | `DIGEST_DAILY_CRON` (既定`0 7 * * *`) | ✅ **オプション** | DB (イベント・メトリクス) + LLM |
| `digest_weekly` | **Cron** | 週次ダイジェスト生成 | `DIGEST_WEEKLY_CRON` (既定`0 8 * * 0`) | ✅ **オプション** | DB + LLM |
| `digest_monthly` | **Cron** | 月次ダイジェスト生成 | `DIGEST_MONTHLY_CRON` (既定`5 0 1 * *`) | ✅ **オプション** | DB + LLM |

### 💾 データベーススキーマ

| テーブル | 用途 | 主要カラム | レコード保持 |
|--------|------|----------|----------|
| **vcenters** | vCenter接続情報 | id, name, host, port, username (暗号化), password (暗号化), is_enabled | 手動削除まで保持 |
| **events** | イベント本体 | id, vcenter_id, occurred_at, event_type, message, severity, user_name, entity_name/type, **notable_score** (計算値), user_comment, vmware_key | `EVENT_RETENTION_DAYS` (既定7日) で自動削除 |
| **metric_samples** | ホストメトリクス時系列 | id, vcenter_id, sampled_at, entity_type, entity_moid, entity_name, metric_key, value (%) | `METRIC_RETENTION_DAYS` (既定7日) で自動削除 |
| **event_score_rules** | イベント種別スコア調整 | id, event_type, score_delta (加算値) | 手動削除まで保持（変更時は関連イベントスコア再計算） |
| **event_type_guides** | イベント種別説明 | id, event_type, general_meaning, typical_causes, remediation, action_required | 手動削除まで保持 |
| **digest_records** | 生成済みダイジェスト | id, period_start/end, kind (daily/weekly/monthly), body_markdown, status, error_message, llm_model | 手動削除まで保持 |
| **ingestion_state** | 取得進捗カーソル | id, vcenter_id, kind (event/metric), cursor_value | イベント・メトリクス再ポーリング時に更新 |

---

## 3. LLM 連携機能

### ✅ LLM を使用する機能

#### 1. ダイジェスト要約（ベータ、オプション）

**概要**: 日次/週次/月次の定期実行または手動実行時に、LLM がイベント・メトリクス集計データを分析し、要約ブロック（`## LLM 要約`）を自動生成する。

**処理フロー**:
```
イベント・メトリクス集計 
  → JSON化 
  → Jinja2テンプレート処理 
  → LLM送信 
  → `## LLM 要約` 追記 
  → Markdown保存
```

**対応 LLM プロバイダー**:

| プロバイダ | 設定値 | 用途 | 実装 | 備考 |
|----------|-------|------|-----|-----|
| **OpenAI API** | `LLM_DIGEST_PROVIDER=openai_compatible`, `LLM_DIGEST_BASE_URL=https://api.openai.com/v1` | クラウド LLM（gpt-4o-mini 推奨） | LangChain (`ChatOpenAI`) | 有償 |
| **Ollama** (ローカル) | `LLM_DIGEST_PROVIDER=openai_compatible`, `LLM_DIGEST_BASE_URL=http://127.0.0.1:11434/v1` | ローカルLLM（llama3.2等） | LangChain (`ChatOpenAI`) | 無償、完全ローカル実行 |
| **LM Studio** (ローカル) | `LLM_DIGEST_PROVIDER=openai_compatible` + 互換エンドポイント | ローカルLLM | LangChain (`ChatOpenAI`) | 無償、GUI付き |
| **Google Gemini API** | `LLM_DIGEST_PROVIDER=gemini`, `LLM_DIGEST_API_KEY=...` | Google生成AI API | LangChain (`ChatGoogleGenerativeAI`) | 有償 |

**❌ 非対応**:
- `LLM_DIGEST_PROVIDER=copilot_cli` は **設定不可**（ダイジェストは LangChain ベースのみ対応、Copilot CLI は不対応）

**設定例**:
```bash
# OpenAI
LLM_DIGEST_PROVIDER=openai_compatible
LLM_DIGEST_BASE_URL=https://api.openai.com/v1
LLM_DIGEST_MODEL=gpt-4o-mini
LLM_DIGEST_API_KEY=sk-...

# Ollama ローカル
LLM_DIGEST_PROVIDER=openai_compatible
LLM_DIGEST_BASE_URL=http://127.0.0.1:11434/v1
LLM_DIGEST_MODEL=llama3.2
LLM_DIGEST_API_KEY=ollama  # ダミー値
```

**特記**:
- `LLM_DIGEST_API_KEY` が空の場合、テンプレートのみで LLM 呼び出しなし
- Jinja2 テンプレート (`DIGEST_TEMPLATE_PATH`) で出力形式をカスタマイズ可能
- 週次・月次は種別別テンプレート指定可能 (`DIGEST_TEMPLATE_WEEKLY_PATH` / `DIGEST_TEMPLATE_MONTHLY_PATH`)

---

#### 2. チャット（期間コンテキスト付き）

**概要**: フロントエンドのチャットパネルでユーザーがメッセージ入力 → バックエンドが イベント・メトリクス・会話ターン を集計・加工して **LLM送信** → 応答表示。

**処理フロー**:
```
ユーザーメッセージ + 期間選択 
  → イベント・メトリクス集計 
  → コンテキスト加工（匿名化等） 
  → LLM送信 
  → 応答表示 + メタデータ返却
```

**入力コンテキスト**:
- イベント集計データ（種別別件数・要注意イベント）
- メトリクス時系列データ（CPU/メモリ/ディスク/ネットワーク、オプション選択）
- 会話履歴（最新20ターン）
- タイムゾーン・vCenter名・ホスト名等（オプション匿名化）

**対応 LLM プロバイダー**:

| プロバイダ | チャット対応 | ダイジェスト対応 | 実装 | 特記 |
|----------|------------|--------------|-----|-----|
| **OpenAI互換** | ✅ | ✅ | LangChain | Chat Completions形式 |
| **Google Gemini** | ✅ | ✅ | LangChain | 互換性注意（トークン計算が異なる場合あり） |
| **GitHub Copilot CLI** | ✅ | ❌ | github-copilot-sdk | **チャット専用**、ダイジェスト非対応 |

**認証方式（Copilot CLI の場合）**:

| 方式 | 設定値 | 特記 |
|-----|-------|-----|
| **PAT渡す** | `LLM_COPILOT_CLI_SESSION_AUTH=false` (既定) | GitHub Personal Access Token（⚠️ 一部モデルで 400 エラー拒否） |
| **CLI セッション** | `LLM_COPILOT_CLI_SESSION_AUTH=true` | マシン上の `gh auth login` / Copilot CLI ログインセッションのみ使用（推奨、PAT不要） |

**トークン管理**:
- `LLM_CHAT_MAX_INPUT_TOKENS` (既定32000) でLLM入力を制限
- 超過時は `json_truncated=true` をメタデータで返却

**トレース機能**（オプション）:
- `LANGSMITH_TRACING_ENABLED=true` で LangSmith にプロンプト・応答を送信（開発・検証用）
- `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT` で設定

---

### ❌ LLM を使わない機能

以下の機能は LLM と無関係に動作する。

| 機能カテゴリ | 機能名 | 説明 | 処理方式 | LLM不要 |
|-----------|-------|------|--------|---------|
| **データ表示** | 概要サマリー | vCenter数・イベント件数・TOP要注意イベント・TOP高負荷ホスト表示 | DB クエリ + 集計 | ✅ |
| | イベント一覧 | 時系列・キーワード検索、フィルタ、ページネーション | DB クエリのみ | ✅ |
| | メトリクスグラフ | CPU/メモリ等メトリクスの時系列グラフ表示 | vCenter データの可視化 | ✅ |
| **ダイジェスト** | テンプレート生成 | Jinja2 テンプレート + コンテキスト変数を結合し Markdown 生成 | テンプレート処理のみ | ✅ |
| **設定管理** | vCenter 登録 | vCenter ホスト・認証情報の登録・更新・削除 | pyVmomi API呼び出し + DB操作 | ✅ |
| | 接続テスト | vCenter への接続テスト | pyVmomi API呼び出し | ✅ |
| | イベント種別ガイド | 説明・原因・対処の CRUD | DB 管理のみ | ✅ |
| | スコアルール | スコア調整ルール管理 + イベントスコア再計算 | DB + 再計算ロジック | ✅ |
| | チャットプロンプト | チャット用サンプルプロンプト管理 | DB 管理のみ | ✅ |
| **定期実行** | イベント取得 | vCenter からイベント定期ポーリング | pyVmomi API + DB INSERT | ✅ |
| | メトリクス取得 | vCenter からホストメトリクス定期サンプリング | pyVmomi API + DB INSERT | ✅ |
| | データ削除 | 期限切れイベント・メトリクスの自動削除 | DB DELETE | ✅ |

---

### 🔐 LLM セキュリティ・匿名化

| 機能 | 説明 | 設定 | デフォルト |
|-----|------|------|---------|
| **入力匿名化** | vCenter名・ホスト名・IP等をハッシュ化して LLM に送信 | `LLM_ANONYMIZATION_ENABLED` | `true` (オン) |
| **応答逆変換** | チャット応答・ダイジェスト LLM 要約は逆変換して実名に戻す | 自動（サーバ側処理） | 有効 |
| **ツール権限拒否** | サーバAPI経由では LLM の外部ツール実行を許可しない | SDK 権限ハンドラ | 拒否 |
| **暗号化保存** | vCenter 認証情報（username, password）を DB で暗号化保存 | 自動 | 有効 |

---

## 4. 技術スタック

### バックエンド

| 領域 | 技術 | 用途 |
|-----|------|------|
| **Web Framework** | FastAPI | 非同期API、自動 OpenAPI ドキュメント |
| **ORM** | SQLAlchemy (async) | DB操作（PostgreSQL/SQLite） |
| **DB マイグレーション** | Alembic | スキーマ管理・バージョン管理 |
| **vCenter接続** | pyVmomi | イベント・メトリクス取得（VMware API） |
| **定期実行** | APScheduler | Cron / Interval ジョブ |
| **LLM** | LangChain | OpenAI/Gemini 統合 |
| **LLM (Copilot CLI)** | github-copilot-sdk | Copilot CLI プロセス経由 |
| **LLM トレース** | LangSmith | プロンプト・応答ロギング（オプション） |
| **テンプレート** | Jinja2 | ダイジェスト Markdown 生成 |
| **トークンカウント** | tiktoken | LLM入力トークン数計算 |
| **テスト** | pytest | ユニットテスト |
| **コード品質** | ruff | リント・フォーマット |
| **非同期実行** | asyncio | 非同期処理 |

### フロントエンド

| 領域 | 技術 | 用途 |
|-----|------|------|
| **ビルドツール** | Vite | 開発・本番ビルド、HMR（Hot Module Reload） |
| **言語** | TypeScript | 型安全開発 |
| **UI フレームワーク** | React | SPA 構築 |
| **グラフ表示** | Recharts | メトリクス時系列グラフ |
| **ブラウザ保存** | localStorage | 設定・チャット履歴・ローカル永続化 |
| **通信** | Fetch API | REST API呼び出し |
| **E2E テスト** | Playwright | 画面キャプチャ、自動テスト |
| **パッケージ管理** | npm | 依存関係管理 |

### データベース

| DB | 用途 | 推奨環境 |
|----|------|--------|
| **PostgreSQL** | 本番推奨 | マルチユーザー、高スケーラビリティ |
| **SQLite** | 開発・テスト推奨 | シングルノード、セットアップ不要 |

---

## 5. 機能マトリクス

### 機能 × LLM連携

| 機能カテゴリ | 機能名 | LLM必須 | LLM推奨 | LLM不要 |
|-----------|-------|--------|--------|--------|
| **データ表示** | 概要サマリー | | | ✅ |
| | イベント一覧 | | | ✅ |
| | メトリクスグラフ | | | ✅ |
| **ダイジェスト** | テンプレート生成 | | | ✅ |
| | LLM 要約追記 | | ✅ | |
| **チャット** | LLM 対話 | ✅ | | |
| **設定管理** | vCenter 登録 | | | ✅ |
| | イベント種別ガイド | | | ✅ |
| | スコアルール | | | ✅ |
| | チャットプロンプト | | | ✅ |
| **定期実行** | イベント取得 | | | ✅ |
| | メトリクス取得 | | | ✅ |
| | データ削除 | | | ✅ |
| | ダイジェスト生成（基本） | | | ✅ |
| | ダイジェスト生成（LLM要約） | | ✅ | |

---

## 6. デプロイ構成

### 単一コンテナ（Docker Compose）

```yaml
# docker-compose.sqlite.yml（本番向けシンプル構成）
services:
  app:
    # FastAPI + React SPA
    # localhost:8000 で UI & API 提供
    environment:
      DATABASE_URL: sqlite+aiosqlite:///./data/vea.db
      LLM_DIGEST_PROVIDER: (オプション)
      LLM_CHAT_PROVIDER: (オプション)

# docker-compose.postgres.yml（高可用性向け）
services:
  app:
    # FastAPI + React SPA
    environment:
      DATABASE_URL: postgresql+asyncpg://user:pass@postgres/vcenter_event_assistant
  postgres:
    # PostgreSQL 14+
    environment:
      POSTGRES_PASSWORD: (設定必須)
```

### 本番環境（リバースプロキシ）

```
Internet
   ↓
[リバースプロキシ (Nginx/Traefik)]
   ├─ TLS 終了
   ├─ 認証 (OAuth/OIDC)
   ├─ ネットワーク制限
   └─ Rate Limiting
   ↓
[FastAPI + React SPA (http://localhost:8000)]
   ├─ /api/* エンドポイント
   └─ UI 配信（frontend/dist）
```

---

## 7. 関連ドキュメント

- **アーキテクチャ**: [docs/architecture.md](architecture.md)
- **フロントエンド詳細**: [docs/frontend.md](frontend.md)
- **開発者向けガイド**: [docs/development.md](development.md)
- **チャット機能詳細**: [docs/chat.md](chat.md)
- **現状実装ベースのプラン**: [docs/plans/2026-03-21-vcenter-event-assistant-as-built.md](plans/2026-03-21-vcenter-event-assistant-as-built.md)

