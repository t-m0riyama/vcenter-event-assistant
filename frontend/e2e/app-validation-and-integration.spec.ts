import { expect, test } from '@playwright/test'
import { expectErrorBanner, expectNoErrorBanner } from './helpers'

test.describe('グラフ・表示期間バリデーション（高）', () => {
  test('片側だけ入力するとエラーバナーが出る', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'グラフ' }).click()

    const rangeDetails = page.locator('details.metrics-panel__range-details')
    await rangeDetails.locator('summary').click()
    // デフォルトは直近24時間で終端も埋まっているため、片側のみにするには終了を空にする
    await rangeDetails.getByLabel('終了日').fill('')
    await rangeDetails.getByLabel('終了時刻').fill('')
    await rangeDetails.getByLabel('開始日').fill('2025-01-01')

    await expectErrorBanner(
      page,
      'グラフの表示期間は開始・終了を両方入力するか、両方空にしてください（片方だけでは指定できません）。',
    )
  })
})

test.describe('スコアルール・空追加（高）', () => {
  test('イベント種別が空のまま追加するとバナーが出る', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: '設定' }).click()
    await page.getByRole('button', { name: 'スコアルール' }).click()

    await page.getByRole('button', { name: '追加' }).click()

    await expectErrorBanner(page, 'イベント種別を入力してください')
  })
})

test.describe('イベント・期間バリデーション（高）', () => {
  test('開始が終了より後だとバナーが出る', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'イベント' }).click()

    await page
      .locator('main details.toolbar__filters-details')
      .filter({ hasText: '絞り込み条件' })
      .locator('summary')
      .click()

    await page.getByLabel('開始日').fill('2025-01-10')
    await page.getByLabel('終了日').fill('2025-01-05')

    await expectErrorBanner(page, '開始は終了より前の時刻にしてください。')
  })
})

test.describe('イベント・0 件ページング（高）', () => {
  test('前へ・次へが無効', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'イベント' }).click()

    await expect(page.getByText('全 0 件')).toBeVisible()
    await expect(page.getByRole('button', { name: '前へ' })).toBeDisabled()
    await expect(page.getByRole('button', { name: '次へ' })).toBeDisabled()
    await expectNoErrorBanner(page)
  })
})

test.describe('リロード（中）', () => {
  test('再読み込み後も主要 UI が表示されエラーが出ない', async ({ page }) => {
    await page.goto('/')
    await page.reload()

    await expect(
      page.getByRole('heading', { name: 'vCenter Event Assistant' }),
    ).toBeVisible()
    await expectNoErrorBanner(page)
  })
})

test.describe('API スモーク（中）', () => {
  test('/health と /api/config が 200', async ({ request }) => {
    const health = await request.get('/health')
    expect(health.status()).toBe(200)

    const config = await request.get('/api/config')
    expect(config.status()).toBe(200)
  })
})

test.describe('スコアルール・追加成功（中）', () => {
  test('一意のイベント種別を追加すると一覧に表示される', async ({ page }) => {
    const eventType = `e2e.rule.${Date.now()}`

    await page.goto('/')
    await page.getByRole('button', { name: '設定' }).click()
    await page.getByRole('button', { name: 'スコアルール' }).click()

    await page.getByLabel('イベント種別（完全一致）').fill(eventType)
    await page.getByRole('button', { name: '追加' }).click()

    await expect(page.getByRole('row', { name: new RegExp(eventType) })).toBeVisible()
    await expectNoErrorBanner(page)
  })
})
