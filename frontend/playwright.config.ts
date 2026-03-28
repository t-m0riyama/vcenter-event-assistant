import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Playwright 設定（`frontend/e2e` 全テスト共通）。
 *
 * **既定の E2E:** `PLAYWRIGHT_USE_EXISTING_SERVER` が未設定のとき、`webServer` で
 * テスト専用の uvicorn を新規起動する（`E2E_PORT`、既定は 9323）。開発用の
 * `localhost:8000` とは別ポートで衝突しない。
 *
 * **ドキュメント用スクリーンショット**（`docs/images`）は、リポジトリルートの
 * `uv run scripts/capture_ui_screenshots.py` が既定で既起動の `http://127.0.0.1:8000`
 * に接続する想定（Playwright は API を起動しない）。
 *
 * 手元の既起動 API だけに E2E を向けたいときは `PLAYWRIGHT_USE_EXISTING_SERVER=1` と
 * `E2E_PORT` または `E2E_BASE_URL` を設定する。
 *
 * **ドキュメント用 PNG を Playwright が起動して取得するとき**（`capture_ui_screenshots.py --spawn-server` /
 * `npm run screenshots:spawn`）だけ、環境変数 `SCREENSHOT_E2E_SEED=1` を付与する。通常の `npm run e2e` では
 * 付けず空 DB で検証する。
 *
 * @see リポジトリルートの `docs/development.md`（ドキュメント用キャプチャと E2E の前提）
 */
const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.join(__dirname, '..')
const port = process.env.E2E_PORT ?? '9323'
/** 既に起動済みのサーバーに向ける場合は `E2E_BASE_URL` または `E2E_PORT` で上書き */
const baseURL =
  process.env.E2E_BASE_URL?.replace(/\/$/, '') ?? `http://127.0.0.1:${port}`

/**
 * 手元で API が動いているだけに E2E を向けたいときは、サーバー起動を省略する。
 * 例: `PLAYWRIGHT_USE_EXISTING_SERVER=1 E2E_PORT=8000 npx playwright test`
 */
const useExistingServerOnly = process.env.PLAYWRIGHT_USE_EXISTING_SERVER === '1'

/**
 * E2E は `frontend/dist` を uvicorn が同一オリジンで配信する前提。
 * `npm run e2e` が先に `npm run build` を実行する。
 */
export default defineConfig({
  testDir: './e2e',
  /** `screenshots.spec.ts` はドキュメント用でシード DB を前提とする。`npm run e2e` では除外し、`capture_ui_screenshots.py` / `npm run screenshots*` が `E2E_RUN_SCREENSHOTS_SPEC=1` を付けて実行する。 */
  testIgnore:
    process.env.E2E_RUN_SCREENSHOTS_SPEC === '1' ? [] : ['**/screenshots.spec.ts'],
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL,
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: useExistingServerOnly
    ? undefined
    : {
        command: `DATABASE_URL=sqlite+aiosqlite:///:memory: SCHEDULER_ENABLED=false uv run uvicorn vcenter_event_assistant.main:create_app --factory --host 127.0.0.1 --port ${port}`,
        cwd: repoRoot,
        url: `${baseURL}/health`,
        reuseExistingServer: !process.env.CI,
        timeout: 120 * 1000,
        env: {
          SCREENSHOT_E2E_SEED: process.env.SCREENSHOT_E2E_SEED ?? '',
        },
      },
})
