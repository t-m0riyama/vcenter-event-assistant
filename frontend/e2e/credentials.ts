import type { APIRequestContext } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * E2E でログインする admin の資格情報（テスト専用の値）。
 *
 * Playwright が起動するサーバー（`webServer`）には、この値を `VEA_BOOTSTRAP_ADMIN_*` として渡し、
 * 空のメモリ DB に初期 admin を作らせる。既起動のサーバーへ向けるとき（スクリーンショット取得など）は
 * `E2E_USERNAME` / `E2E_PASSWORD` でそのサーバーの admin を指定する。
 */
export const E2E_USERNAME = process.env.E2E_USERNAME ?? 'e2e-admin'
export const E2E_PASSWORD = process.env.E2E_PASSWORD ?? 'e2e-admin-password'

/** 資格情報を環境変数で明示したか（既起動のサーバーでは既定値の admin は作られないため必須）。 */
export const CREDENTIALS_FROM_ENV = Boolean(process.env.E2E_USERNAME && process.env.E2E_PASSWORD)

/** Playwright がサーバーを起動せず、既起動のサーバーに向けているか（`playwright.config.ts` と同じ判定）。 */
export const USING_EXISTING_SERVER = process.env.PLAYWRIGHT_USE_EXISTING_SERVER === '1'

/** 対象サーバーで認証が有効か（認証が無効なら `/api/auth/me` が `auth_enabled: false` を返す）。 */
export async function isAuthEnabled(request: APIRequestContext): Promise<boolean> {
  const me = await request.get('/api/auth/me')
  if (!me.ok()) return true
  return (await me.json()).auth_enabled !== false
}

const __dirname = path.dirname(fileURLToPath(import.meta.url))

/** `auth.setup.ts` がログイン後の Cookie を保存し、各 spec が使い回す（gitignore 済み）。 */
export const AUTH_STATE_FILE = path.join(__dirname, '.auth', 'admin.json')
