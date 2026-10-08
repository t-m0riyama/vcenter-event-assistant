import { expect, test } from '@playwright/test'
import { E2E_USERNAME, isAuthEnabled, USING_EXISTING_SERVER } from './credentials'

test.describe('ユーザー管理', () => {
  test.beforeEach(async ({ request }) => {
    test.skip(!(await isAuthEnabled(request)), 'VEA_AUTH_ENABLED=false のサーバー')
  })

  test('admin は一覧で自分を確認できる', async ({ page }) => {
    await page.goto('/#/settings/users')
    await expect(page.getByRole('heading', { name: 'ローカルユーザーの作成' })).toBeVisible()
    const self = page.locator('tr', { has: page.getByText('（あなた）') })
    await expect(self).toContainText(E2E_USERNAME)
    await expect(self.getByRole('button', { name: '削除' })).toHaveCount(0)
    await expect(page.locator('.error-banner, [role="alert"]')).toHaveCount(0)
  })

  test('ユーザーを作成して削除する', async ({ page }) => {
    // 既起動のサーバー（運用中のデータ）にはユーザーを作らない
    test.skip(USING_EXISTING_SERVER, '既起動のサーバー')
    const username = `e2e-viewer-${Date.now()}`
    await page.goto('/#/settings/users')
    await page.getByLabel('ユーザー名').fill(username)
    await page.getByLabel('初期パスワード', { exact: true }).fill('e2e-viewer-password')
    await page.getByLabel('初期パスワード（確認）').fill('e2e-viewer-password')
    await page.getByRole('button', { name: '作成' }).click()
    await expect(page.getByRole('status')).toContainText(`ユーザー ${username} を作成しました。`)

    const row = page.locator('tr', { has: page.getByText(username, { exact: true }) })
    await expect(row).toContainText('閲覧者')
    page.once('dialog', (dialog) => void dialog.accept())
    await row.getByRole('button', { name: '削除' }).click()
    await expect(page.getByRole('status')).toContainText(`${username} を削除しました。`)
    await expect(row).toHaveCount(0)
  })
})
