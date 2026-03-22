# 開発者向けメモ

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
