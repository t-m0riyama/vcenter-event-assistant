import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
/** リポジトリルートの `docs/images`（`frontend/e2e` → 2 階層上がルート） */
const docsImagesDir = path.join(__dirname, '../../docs/images')

/**
 * ドキュメント用に主要タブの画面を `docs/images` に PNG 保存する。
 * 再取得手順はリポジトリルートの `docs/development.md` を参照。
 */
test('主要画面のスクリーンショットを docs/images に保存', async ({ page }) => {
  mkdirSync(docsImagesDir, { recursive: true })

  await page.goto('/')
  await expect(
    page.getByRole('heading', { name: 'vCenter Event Assistant' }),
  ).toBeVisible()

  await page.getByRole('button', { name: '概要' }).click()
  await expect(page.getByText('登録 vCenter', { exact: true })).toBeVisible()
  await page.screenshot({
    path: path.join(docsImagesDir, 'summary.png'),
    fullPage: true,
  })

  await page.getByRole('button', { name: 'イベント' }).click()
  await expect(page.getByText('全 0 件')).toBeVisible()
  await page.screenshot({
    path: path.join(docsImagesDir, 'events.png'),
    fullPage: true,
  })

  await page.getByRole('button', { name: 'グラフ' }).click()
  await expect(page.getByLabel('vCenter')).toBeVisible()
  await expect(page.getByLabel('メトリクスキー')).toBeVisible()
  await page.screenshot({
    path: path.join(docsImagesDir, 'metrics.png'),
    fullPage: true,
  })

  await page.getByRole('button', { name: '設定' }).click()
  await page.getByRole('button', { name: '一般' }).click()
  await expect(page.getByLabel('外観')).toBeVisible()
  await page.screenshot({
    path: path.join(docsImagesDir, 'settings-general.png'),
    fullPage: true,
  })

  await page.getByRole('button', { name: 'vCenter' }).click()
  await expect(page.getByRole('heading', { name: '登録' })).toBeVisible()
  await page.screenshot({
    path: path.join(docsImagesDir, 'settings-vcenters.png'),
    fullPage: true,
  })

  await page.getByRole('button', { name: 'スコアルール' }).click()
  await expect(
    page.getByText(
      'イベント種別（event_type）ごとに、ルールベースのスコアへ加算する値を設定します。',
    ),
  ).toBeVisible()
  await page.screenshot({
    path: path.join(docsImagesDir, 'settings-score-rules.png'),
    fullPage: true,
  })
})
