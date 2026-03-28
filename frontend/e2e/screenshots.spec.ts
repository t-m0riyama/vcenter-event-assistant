import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
/** リポジトリルートの `docs/images`（`frontend/e2e` → 2 階層上がルート） */
const docsImagesDir = path.join(__dirname, '../../docs/images')

/** ドキュメント用 PNG の共通ピクセル寸法（`fullPage: false` のビューポートと一致） */
const DOC_SCREENSHOT_WIDTH = 1280
const DOC_SCREENSHOT_HEIGHT = 720

/**
 * ドキュメント用に主要タブの画面を `docs/images` に PNG 保存する。
 * 再取得手順はリポジトリルートの `docs/development.md` を参照。
 *
 * バックエンドは `SCREENSHOT_E2E_SEED=1`（Playwright `webServer` 既定）で
 * ガイド付きイベント等をメモリ DB に挿入する。
 */
test('主要画面のスクリーンショットを docs/images に保存', async ({ page }) => {
  mkdirSync(docsImagesDir, { recursive: true })

  await page.goto('/')
  await page.setViewportSize({
    width: DOC_SCREENSHOT_WIDTH,
    height: DOC_SCREENSHOT_HEIGHT,
  })
  await expect(
    page.getByRole('heading', { name: 'vCenter Event Assistant' }),
  ).toBeVisible()

  await page.getByRole('button', { name: '概要' }).click()
  await expect(page.getByText('登録 vCenter', { exact: true })).toBeVisible()
  await page.screenshot({
    path: path.join(docsImagesDir, 'summary.png'),
    fullPage: false,
  })

  await page.getByRole('button', { name: 'イベント' }).click()
  await expect(page.getByText(/全 \d+ 件/)).toBeVisible()
  await page.screenshot({
    path: path.join(docsImagesDir, 'events.png'),
    fullPage: false,
  })

  const guideDetails = page.locator('td.event-type-guide-cell details.event-type-guide-details').first()
  await guideDetails.locator('summary').click()
  await expect(page.getByText('一般的な意味', { exact: true }).first()).toBeVisible()
  await guideDetails.scrollIntoViewIfNeeded()
  await page.screenshot({
    path: path.join(docsImagesDir, 'events-event-type-guide-expanded.png'),
    fullPage: false,
  })

  await page.getByRole('button', { name: 'グラフ' }).click()
  await expect(page.getByLabel('vCenter')).toBeVisible()
  await expect(page.getByLabel('メトリクスキー')).toBeVisible()
  // シード済みメトリクスで折れ線が描画されるまで待つ（空グラフのキャプチャを避ける）
  await expect(page.locator('.recharts-line')).toBeVisible({ timeout: 20_000 })
  await page.screenshot({
    path: path.join(docsImagesDir, 'metrics.png'),
    fullPage: false,
  })

  await page.getByRole('button', { name: '設定' }).click()
  await page.getByRole('button', { name: '一般' }).click()
  await expect(page.getByLabel('外観')).toBeVisible()
  await page.screenshot({
    path: path.join(docsImagesDir, 'settings-general.png'),
    fullPage: false,
  })

  await page.getByRole('button', { name: 'vCenter' }).click()
  await expect(page.getByRole('heading', { name: '登録' })).toBeVisible()
  await page.screenshot({
    path: path.join(docsImagesDir, 'settings-vcenters.png'),
    fullPage: false,
  })

  await page.getByRole('button', { name: 'スコアルール' }).click()
  await expect(
    page.getByText(
      'イベント種別（event_type）ごとに、ルールベースのスコアへ加算する値を設定します。',
    ),
  ).toBeVisible()
  await page.screenshot({
    path: path.join(docsImagesDir, 'settings-score-rules.png'),
    fullPage: false,
  })

  await page.getByRole('button', { name: 'イベント種別ガイド' }).click()
  await expect(
    page.getByText('イベント種別（event_type、収集ログの種別文字列と完全一致）ごとに', {
      exact: false,
    }),
  ).toBeVisible()
  await page.locator('.event-type-guides-list').scrollIntoViewIfNeeded()
  await page.screenshot({
    path: path.join(docsImagesDir, 'settings-event-type-guides-list.png'),
    fullPage: false,
  })
})
