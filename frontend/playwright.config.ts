import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.join(__dirname, '..')
const port = process.env.E2E_PORT ?? '9323'
const baseURL = `http://127.0.0.1:${port}`

/**
 * E2E は `frontend/dist` を uvicorn が同一オリジンで配信する前提。
 * `npm run e2e` が先に `npm run build` を実行する。
 */
export default defineConfig({
  testDir: './e2e',
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
  webServer: {
    command: `DATABASE_URL=sqlite+aiosqlite:///:memory: SCHEDULER_ENABLED=false uv run uvicorn vcenter_event_assistant.main:create_app --factory --host 127.0.0.1 --port ${port}`,
    cwd: repoRoot,
    url: `${baseURL}/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 120 * 1000,
  },
})
