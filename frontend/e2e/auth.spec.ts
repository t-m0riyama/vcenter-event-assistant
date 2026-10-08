import { expect, test } from '@playwright/test'
import { E2E_PASSWORD, E2E_USERNAME } from './credentials'

// ログイン画面そのものを確かめるので、保存済みのセッションは使わない
test.use({ storageState: { cookies: [], origins: [] } })

test.describe('ログイン', () => {
  test('未ログインならログイン画面だけを出す', async ({ page }) => {
    await page.goto('/#/events')
    await expect(page.getByRole('form', { name: 'ログイン' })).toBeVisible()
    await expect(page.locator('nav.tabs')).toHaveCount(0)
  })

  test('誤ったパスワードでは入れない', async ({ page }) => {
    await page.goto('/')
    await page.getByLabel('ユーザー名').fill(E2E_USERNAME)
    await page.getByLabel('パスワード').fill('wrong password')
    await page.getByRole('button', { name: 'ログイン' }).click()
    await expect(page.getByRole('alert')).toContainText('ユーザー名またはパスワードが正しくありません')
    await expect(page.locator('nav.tabs')).toHaveCount(0)
  })

  test('ログインしてアプリを使い、ログアウトするとログイン画面に戻る', async ({ page }) => {
    await page.goto('/')
    await page.getByLabel('ユーザー名').fill(E2E_USERNAME)
    await page.getByLabel('パスワード').fill(E2E_PASSWORD)
    await page.getByRole('button', { name: 'ログイン' }).click()

    await expect(page.getByRole('heading', { name: 'vCenter Event Assistant' })).toBeVisible()
    await expect(page.locator('.user-menu__role')).toHaveText('管理者')
    await page.getByRole('button', { name: 'イベント' }).click()
    await expect(page.locator('[role="alert"]')).toHaveCount(0)

    await page.getByRole('button', { name: 'ログアウト' }).click()
    await expect(page.getByRole('form', { name: 'ログイン' })).toBeVisible()
    // 再読み込みしてもログイン画面のまま（セッションは失効している）
    await page.reload()
    await expect(page.getByRole('form', { name: 'ログイン' })).toBeVisible()
  })
})
