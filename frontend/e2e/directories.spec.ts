import { expect, test } from '@playwright/test'
import { isAuthEnabled } from './credentials'

test.describe('認証ディレクトリ', () => {
  test.beforeEach(async ({ request }) => {
    test.skip(!(await isAuthEnabled(request)), 'VEA_AUTH_ENABLED=false のサーバー')
  })

  test('admin は一覧を開け、つながらないサーバの接続試験は接続の段階で失敗する', async ({ page }) => {
    await page.goto('/#/settings/directories')
    await expect(page.getByRole('button', { name: 'ディレクトリを追加' })).toBeVisible()
    await expect(page.locator('.error-banner, [role="alert"]')).toHaveCount(0)

    // 接続試験は保存しないので、既起動のサーバーでも試せる。ポート 1 には LDAP サーバがいない
    await page.getByRole('button', { name: 'ディレクトリを追加' }).click()
    const form = page.getByRole('region', { name: 'ディレクトリの設定' })
    await form.getByLabel('名前').fill('e2e-unreachable')
    await form.getByLabel(/^サーバ（1 行に 1 つ/).fill('ldaps://127.0.0.1:1')
    await form.getByLabel('検索ベース').fill('dc=example,dc=com')
    await form.getByLabel('タイムアウト（秒）').fill('2')
    await form.getByRole('button', { name: '接続試験' }).click()

    const result = form.getByLabel('接続試験の結果')
    await expect(result).toContainText('接続試験に失敗しました。')
    await expect(result).toContainText('接続')
    await form.getByRole('button', { name: 'キャンセル' }).click()
    await expect(form).toHaveCount(0)
  })
})
