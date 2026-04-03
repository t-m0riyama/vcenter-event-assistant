# 開発者向けメモ

## 期間コンテキスト付きチャット

- `POST /api/chat` … 本文 JSON で `from` / `to`（UTC）、`messages`（`role`: `user` | `assistant`、`content`）。**最後の要素は `user`**。任意で `vcenter_id`（単一 vCenter に絞る）、`top_notable_min_score`（既定 1）。**期間メトリクス（いずれも既定 `false`、追加 DB クエリあり）:** `include_period_metrics_cpu`、`include_period_metrics_memory`、`include_period_metrics_disk_io`、`include_period_metrics_network_io`。オンにしたカテゴリだけ `MetricSample` を期間・`vcenter_id` で読み、時間バケット平均で `period_metrics` として LLM コンテキストにマージする（チャット用の `digest_context` からはホスト別 CPU/メモリのピーク一覧は含めない）。**メトリクストグルが 1 つでもオン**のときは、同じバケット幅で `events` を集計した `event_time_buckets`（件数 0 のバケットは省略）もマージする。バッチダイジェストには含めない。イベント集約は `build_digest_context` と同じ（期間は DB 上 **UTC の `[from, to)`**）。会話履歴はクライアントが送るだけでサーバーは保持しない。応答は `assistant_content` と `error`（LLM 失敗時は前者が空で後者に短文）。**`llm_context`**（省略可）に、LLM 直前の目安として `json_truncated`（JSON をトークン上限で切り詰めたか）、`estimated_input_tokens` / `max_input_tokens`、`message_turns` が入る。サーバーログにも `json_truncated` 等が出る。

環境変数は **ダイジェストと同じ `LLM_*`**（`.env.example` の LLM 節を参照）。`LLM_API_KEY` が空のときは **503**。

## LLM 実装（バックエンド）

ダイジェスト要約（`augment_digest_with_llm`）と期間チャット（`run_period_chat`）は **LangChain** の `ChatOpenAI`（`LLM_PROVIDER=openai_compatible`）または `ChatGoogleGenerativeAI`（`gemini`）を [`llm_factory`](../src/vcenter_event_assistant/services/llm_factory.py) で組み立て、応答本文は `astream` でチャンク連結する。依存は `langchain-core`・`langchain-openai`・`langchain-google-genai`。将来の観測（例: LangSmith）用に、`runnable_config` で `RunnableConfig`（callbacks 等）を渡せる拡張点がある。

## バッチダイジェスト API（実験的）

- `GET /api/digests` … 保存済みダイジェスト一覧（`limit` / `offset`）
- `GET /api/digests/{id}` … 1 件取得
- `POST /api/digests/run` … 手動生成。JSON 省略時は **`kind` と `DIGEST_DISPLAY_TIMEZONE` に基づく直前期間**（日次=直前暦日、週次=直前週、月次=直前月）を対象。`from_time` / `to_time` を両方指定すると任意期間

環境変数は `.env.example` の「Batch digest」を参照。`LLM_API_KEY` 未設定時は集約テンプレートのみで保存され、外部 LLM は呼ばれない。Ollama などローカルの OpenAI 互換 API の例は README の「ダイジェスト用 LLM」と `.env.example` を参照する。

**定期実行:** `DIGEST_DAILY_*` / `DIGEST_WEEKLY_*` / `DIGEST_MONTHLY_*` で種別ごとに有効化と cron（5 フィールド）を指定。`DIGEST_SCHEDULER_ENABLED` / `DIGEST_CRON` は日次向けレガシー名（非推奨）。週次の集計ウィンドウは **`DIGEST_DISPLAY_TIMEZONE` 上で日曜 0:00 始まりの直前に完了した暦週**（7 日）、月次は **その TZ の直前暦月**。手動 `POST /api/digests/run` は任意 `from`/`to` と `kind`、または期間省略で上記と同じ既定窓。

ダイジェスト本文は **Jinja2**（`DIGEST_TEMPLATE_*` / 同梱 `digest.md.j2`）。**任意の** `DIGEST_TEMPLATE_WEEKLY_PATH` / `DIGEST_TEMPLATE_MONTHLY_PATH` は、対応する `kind`（`weekly` / `monthly`）の実行時だけ最優先で読み、未設定または空のときは従来どおり `DIGEST_TEMPLATE_PATH` → `DIR`+`FILE` → 同梱へフォールバックする。**解決順**・PATH 指定時のエラー扱い・**次回の API / スケジュール実行から**テンプレ変更が反映されることは `.env.example` のコメントを参照。**集計期間**は DB 上 **UTC の `[from, to)`** で、**暦の切り口**（日／週／月の境界）は **`DIGEST_DISPLAY_TIMEZONE`（IANA）** で解釈する。テンプレ構文エラーやファイル不可のときは `DigestRecord.status=error` で保存され LLM は呼ばれない。

**件数の上限:** 同梱テンプレでは要注意イベントを `ctx.top_notable_event_groups[:20]` のように**テンプレ内でスライス**している（**種別ごとに 1 エントリ**）。`ctx` に載る**グループ数**は `_TOP_NOTABLE_EVENT_GROUPS_LIMIT`（既定 10）、集約前に DB から読む行の上限は `_TOP_NOTABLE_RAW_FETCH_LIMIT`（既定 200）。テンプレだけ行数を増やしても、集約側の定数を上げない限り **表示は増えない**（必要なら `digest_context.py` の定数を変更する）。

## UI スクリーンショット（`docs/images`）

ドキュメント用の画面キャプチャは Playwright で取得し、`docs/images/*.png` に保存します。テスト定義は `frontend/e2e/screenshots.spec.ts` です。

### ドキュメント用キャプチャと Playwright E2E の前提

| 用途 | 前提 |
|------|------|
| **ドキュメント用 PNG**（本節） | 手元で **既に起動している** `http://127.0.0.1:8000`（API とフロントを同一オリジンで配信）を対象にする。`capture_ui_screenshots.py` の既定では Playwright は API を起動しない。 |
| **`frontend/e2e/*.spec.ts` の E2E** | `npm run e2e` では **テスト専用**の uvicorn を **新規起動**する（既定ポートは環境変数 `E2E_PORT`、既定値は **9323**。開発用 8000 と別）。**`screenshots.spec.ts` はシード DB 前提のため `npm run e2e` の対象外**（ドキュメント取得は `capture_ui_screenshots.py` / `npm run screenshots*`）。設定は [frontend/playwright.config.ts](../frontend/playwright.config.ts)。 |
| **例外** | ドキュメント PNG を 8000 なしで取るときは `--spawn-server` または `npm run screenshots:spawn`（Playwright がメモリ DB＋シードで API を起動。E2E の `webServer` と同系）。 |

### 前提

- リポジトリルートで実行する（`scripts/` の相対パスが正しく解決されること）。
- `frontend` で `npm install` と `npx playwright install`（初回のみ）を済ませる。

### 推奨: `uv run` スクリプト

**既定**は **既に起動しているアプリ**（例: `http://127.0.0.1:8000`）へ接続し、Playwright はサーバーを起動しません。事前に API＋フロント配信を動かしておき、必要なら `npm run build` 後にサーバーを再起動してください。

| コマンド | 内容 |
|---------|------|
| `uv run scripts/capture_ui_screenshots.py` | 既定で `http://127.0.0.1:8000`（`--port` / `--base-url` で変更可）に接続し PNG を更新 |
| `uv run scripts/capture_ui_screenshots.py --build` | 実行前に `frontend` で `npm run build` する |
| `uv run scripts/capture_ui_screenshots.py --port 9000` | 既存サーバーのポートのみ変更 |
| `uv run scripts/capture_ui_screenshots.py --base-url http://127.0.0.1:8000` | 接続先 URL を明示 |
| `uv run scripts/capture_ui_screenshots.py --spawn-server` | Playwright が uvicorn（メモリ DB・`SCREENSHOT_E2E_SEED=1`）を起動。単体テストや CI 向け |

スクリーンショット取得時の接続先は `PLAYWRIGHT_USE_EXISTING_SERVER=1` と `E2E_PORT` または `E2E_BASE_URL` で制御します（上表のドキュメント用キャプチャ向け。E2E 全般の挙動は `frontend/playwright.config.ts` の先頭コメントを参照）。**リポジトリの `docs/images/*.png` を更新するのは `WRITE_DOC_SCREENSHOTS_TO_REPO=1` のときだけ**（`capture_ui_screenshots.py` と `npm run screenshots*` が付与）。未設定で `screenshots.spec.ts` だけを実行した場合は `frontend/test-results/` に出力され、コミット対象の画像は置き換わりません。

### 代替: `frontend` で npm

```bash
cd frontend
npm run screenshots
```

組み込みサーバーで取得する例（`npm run build` 付き）:

```bash
cd frontend
npm run screenshots:spawn
```

ポートを変える例:

```bash
cd frontend
PLAYWRIGHT_USE_EXISTING_SERVER=1 E2E_PORT=9000 npx playwright test e2e/screenshots.spec.ts
```

Windows のコマンドプロンプトでは環境変数の付け方が異なるため、**`uv run scripts/capture_ui_screenshots.py`** の利用を推奨します。

### 出力ファイル

すべて **1280×720 ピクセル**（固定ビューポート・ページ全体ではない）です。**既定で既起動の API に向ける場合**、DB の内容は手元環境に依存します（ガイド列・グラフ・イベント種別一覧など、画面にデータが無いと見え方が変わります）。**`--spawn-server`** で Playwright が API を起動するときだけ `SCREENSHOT_E2E_SEED=1` によりガイド付きイベント・メトリクス時系列などがメモリ DB に挿入されます。

| ファイル名 | 画面 |
|-----------|------|
| `summary.png` | 概要 |
| `events.png` | イベント |
| `events-event-type-guide-expanded.png` | イベント → ガイド列「表示」展開 |
| `metrics.png` | グラフ |
| `settings-general.png` | 設定 → 一般 |
| `settings-vcenters.png` | 設定 → vCenter |
| `settings-score-rules.png` | 設定 → スコアルール |
| `settings-event-type-guides-list.png` | 設定 → イベント種別ガイド（一覧先頭付近） |
