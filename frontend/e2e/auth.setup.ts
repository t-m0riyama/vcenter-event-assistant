import { expect, test as setup } from '@playwright/test'
import { AUTH_STATE_FILE, E2E_PASSWORD, E2E_USERNAME } from './credentials'

/** 画面からログインし、セッション Cookie を保存する（ほかの spec はログイン済みで始まる）。 */
setup('admin でログインする', async ({ page }) => {
  // 認証を無効にしたサーバー（VEA_AUTH_ENABLED=false）ではログイン画面が出ないので、空の状態を保存して終える
  const me = await page.request.get('/api/auth/me')
  if (me.ok() && (await me.json()).auth_enabled === false) {
    await page.context().storageState({ path: AUTH_STATE_FILE })
    return
  }

  await page.goto('/')
  await page.getByLabel('ユーザー名').fill(E2E_USERNAME)
  await page.getByLabel('パスワード').fill(E2E_PASSWORD)
  await page.getByRole('button', { name: 'ログイン' }).click()
  await expect(page.getByRole('button', { name: 'ログアウト' })).toBeVisible()
  await page.context().storageState({ path: AUTH_STATE_FILE })
})
