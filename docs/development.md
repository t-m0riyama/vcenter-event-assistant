# 開発者向けメモ

## バッチダイジェスト API（実験的）

- `GET /api/digests` … 保存済みダイジェスト一覧（`limit` / `offset`）
- `GET /api/digests/{id}` … 1 件取得
- `POST /api/digests/run` … 手動生成。JSON 省略時は **直前の UTC 暦日** を対象。`from_time` / `to_time` を両方指定すると任意期間

環境変数は `.env.example` の「Batch digest」を参照。`LLM_API_KEY` 未設定時は集約テンプレートのみで保存され、外部 LLM は呼ばれない。

**定期実行:** `DIGEST_DAILY_*` / `DIGEST_WEEKLY_*` / `DIGEST_MONTHLY_*` で種別ごとに有効化と cron（5 フィールド）を指定。`DIGEST_SCHEDULER_ENABLED` / `DIGEST_CRON` は日次向けレガシー名（非推奨）。週次の集計ウィンドウは **UTC・日曜 0:00 始まりの直前に完了した暦週**（7 日）、月次は **直前の UTC 暦月**。手動 `POST /api/digests/run` は従来どおり任意 `from`/`to` と `kind`。

ダイジェスト本文は **Jinja2**（`DIGEST_TEMPLATE_*` / 同梱 `digest.md.j2`）。**解決順**・PATH 指定時のエラー扱い・**次回の API / スケジュール実行から**テンプレ変更が反映されることは `.env.example` のコメントを参照。**集計期間**は従来どおり **UTC の `[from, to)`**。**日時の見た目**だけ `DIGEST_DISPLAY_TIMEZONE`（IANA）で変換する。テンプレ構文エラーやファイル不可のときは `DigestRecord.status=error` で保存され LLM は呼ばれない。

**件数の上限:** 同梱テンプレでは要注意イベントなどを `ctx.top_notable_events[:20]` のように**テンプレ内でスライス**しているが、**`ctx` に載る件数は `digest_context.build_digest_context` 側の定数**（例: 上位イベントはクエリで最大 10 件）で決まる。テンプレートだけ行数を増やしても、集約側の上限を上げない限り **DB から渡る行は増えない**（必要なら `digest_context.py` の定数を変更する）。

## UI スクリーンショット（`docs/images`）

ドキュメント用の画面キャプチャは Playwright で取得し、`docs/images/*.png` に保存します。テスト定義は `frontend/e2e/screenshots.spec.ts` です。

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

接続先は `PLAYWRIGHT_USE_EXISTING_SERVER=1` と `E2E_PORT` または `E2E_BASE_URL` で制御します（詳細は `frontend/playwright.config.ts`）。

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
