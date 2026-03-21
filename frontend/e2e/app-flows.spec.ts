import { expect, test } from '@playwright/test'
import { expectNoErrorBanner } from './helpers'

test.describe('設定の全サブタブ', () => {
  test('一般・vCenter・スコアルールで代表 UI が表示されエラーが出ない', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: '設定' }).click()

    await page.getByRole('button', { name: '一般' }).click()
    await expect(
      page.getByText(
        'ライト・ダーク、または OS の表示設定に合わせます。選択はこのブラウザに保存されます。',
      ),
    ).toBeVisible()
    await expect(page.getByLabel('外観')).toBeVisible()
    await expect(
      page.getByText('日時の表示に使うタイムゾーンです。選択はこのブラウザに保存されます。'),
    ).toBeVisible()
    await expectNoErrorBanner(page)

    await page.getByRole('button', { name: 'vCenter' }).click()
    await expect(page.getByRole('heading', { name: '登録' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '一覧' })).toBeVisible()
    await expect(page.getByRole('button', { name: '追加' })).toBeVisible()
    await expectNoErrorBanner(page)

    await page.getByRole('button', { name: 'スコアルール' }).click()
    await expect(
      page.getByText(
        'イベント種別（event_type）ごとに、ルールベースのスコアへ加算する値を設定します。',
      ),
    ).toBeVisible()
    await expect(page.getByRole('heading', { name: '追加' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '一覧' })).toBeVisible()
    await expectNoErrorBanner(page)
  })
})

test.describe('概要（空データ）', () => {
  test('統計と要注意イベントが空表示になる', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: '概要' }).click()

    await expect(page.getByText('登録 vCenter', { exact: true })).toBeVisible()
    await expect(page.getByText('24h イベント', { exact: true })).toBeVisible()
    await expect(page.getByText('24h 要注意（スコア≥40）', { exact: true })).toBeVisible()

    const notableSummary = page.locator('.summary-panel__notable-details summary')
    await expect(notableSummary).toContainText('要注意イベント（上位）')
    await expect(notableSummary).toContainText('該当なし')
    await expectNoErrorBanner(page)
  })
})

test.describe('イベント（空）', () => {
  test('件数 0 と CSV 無効', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'イベント' }).click()

    await expect(page.getByText('全 0 件')).toBeVisible()
    await expect(page.getByRole('button', { name: 'CSV をダウンロード' })).toBeDisabled()
    await expectNoErrorBanner(page)
  })
})

test.describe('グラフ（メトリクスなし）', () => {
  test('空メトリクスと再取得無効', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'グラフ' }).click()

    await expect(page.getByLabel('vCenter')).toBeVisible()
    await expect(page.getByLabel('メトリクスキー')).toBeVisible()
    await expect(page.getByRole('button', { name: '手動で収集' })).toBeVisible()

    await expect(page.getByLabel('メトリクスキー')).toHaveText(/収集済みメトリクスがありません/)
    await expect(page.getByRole('button', { name: '再取得' })).toBeDisabled()
    await expectNoErrorBanner(page)
  })
})

test.describe('タイムゾーン操作', () => {
  test('別のタイムゾーンに切り替えてもエラーが出ない', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: '設定' }).click()
    await page.getByRole('button', { name: '一般' }).click()

    const select = page.getByLabel('表示タイムゾーン')
    const options = await select.locator('option').allTextContents()
    expect(options.length).toBeGreaterThan(1)
    await select.selectOption({ index: 1 })

    await expectNoErrorBanner(page)
  })
})
