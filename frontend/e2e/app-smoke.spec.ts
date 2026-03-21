import { expect, test } from '@playwright/test'

test.describe('アプリのスモーク', () => {
  test('見出し・タブ遷移・設定の一般でエラーが出ない', async ({ page }) => {
    await page.goto('/')

    await expect(
      page.getByRole('heading', { name: 'vCenter Event Assistant' }),
    ).toBeVisible()

    const tabs = ['概要', 'イベント', 'グラフ', '設定'] as const
    for (const name of tabs) {
      await page.getByRole('button', { name }).click()
      await expect(page.locator('[role="alert"]')).toHaveCount(0)
    }

    await page.getByRole('button', { name: '一般' }).click()
    await expect(
      page.getByText(
        'ライト・ダーク、または OS の表示設定に合わせます。選択はこのブラウザに保存されます。',
      ),
    ).toBeVisible()
    await expect(
      page.getByText('日時の表示に使うタイムゾーンです。選択はこのブラウザに保存されます。'),
    ).toBeVisible()
    await expect(page.locator('[role="alert"]')).toHaveCount(0)
  })
})
