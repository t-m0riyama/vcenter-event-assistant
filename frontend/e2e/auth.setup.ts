import { expect, test as setup } from '@playwright/test'
import {
  AUTH_STATE_FILE,
  CREDENTIALS_FROM_ENV,
  E2E_PASSWORD,
  E2E_USERNAME,
  isAuthEnabled,
  USING_EXISTING_SERVER,
} from './credentials'

/** 画面からログインし、セッション Cookie を保存する（ほかの spec はログイン済みで始まる）。 */
setup('admin でログインする', async ({ page }) => {
  // 認証を無効にしたサーバー（VEA_AUTH_ENABLED=false）ではログイン画面が出ないので、空の状態を保存して終える
  if (!(await isAuthEnabled(page.request))) {
    await page.context().storageState({ path: AUTH_STATE_FILE })
    return
  }
  if (USING_EXISTING_SERVER && !CREDENTIALS_FROM_ENV) {
    // 既起動のサーバーには E2E 用の admin が作られていない。ログイン画面で待ち続けず、理由を示して止める
    throw new Error(
      '認証が有効な既起動サーバーに向けています。ログインする admin を環境変数 E2E_USERNAME / E2E_PASSWORD で指定してください。',
    )
  }

  await page.goto('/')
  await page.getByLabel('ユーザー名').fill(E2E_USERNAME)
  await page.getByLabel('パスワード').fill(E2E_PASSWORD)
  await page.getByRole('button', { name: 'ログイン' }).click()
  await expect(page.getByRole('button', { name: 'ログアウト' })).toBeVisible()
  await page.context().storageState({ path: AUTH_STATE_FILE })
})
