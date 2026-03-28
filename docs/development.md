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

| コマンド | 内容 |
|---------|------|
| `uv run scripts/capture_ui_screenshots.py` | `npm run build` のうえ、テスト用サーバー起動付きで E2E を実行し、PNG を更新 |
| `uv run scripts/capture_ui_screenshots.py --existing` | **既に API が動いている**前提。ビルドを省略し、既定で `http://127.0.0.1:8000` に接続 |
| `uv run scripts/capture_ui_screenshots.py -e --port 9000` | 既存サーバー向け。ポートのみ変更 |
| `uv run scripts/capture_ui_screenshots.py -e --base-url http://127.0.0.1:8000` | 既存サーバー向け。ホスト・URL を明示 |

`--existing`（`-e`）利用時は、Playwright が別プロセスでサーバーを立てない（`PLAYWRIGHT_USE_EXISTING_SERVER=1`）。接続先は `E2E_PORT` または `E2E_BASE_URL` で制御します（詳細は `frontend/playwright.config.ts`）。

### 代替: `frontend` で npm

```bash
cd frontend
npm run screenshots
```

既存サーバー向け（Unix 系シェルで `VAR=value command` が使える環境）:

```bash
cd frontend
npm run screenshots:existing
```

ポートを変える例:

```bash
cd frontend
PLAYWRIGHT_USE_EXISTING_SERVER=1 E2E_PORT=9000 npx playwright test e2e/screenshots.spec.ts
```

Windows のコマンドプロンプトでは環境変数の付け方が異なるため、既存サーバー向けは **`uv run scripts/capture_ui_screenshots.py --existing`** の利用を推奨します。

### 出力ファイル

| ファイル名 | 画面 |
|-----------|------|
| `summary.png` | 概要 |
| `events.png` | イベント |
| `metrics.png` | グラフ |
| `settings-general.png` | 設定 → 一般 |
| `settings-vcenters.png` | 設定 → vCenter |
| `settings-score-rules.png` | 設定 → スコアルール |
