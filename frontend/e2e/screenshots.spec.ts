import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
/** リポジトリにコミットするドキュメント PNG 用（`frontend/e2e` → 2 階層上がルート） */
const repoDocsImagesDir = path.join(__dirname, '../../docs/images')
/** `WRITE_DOC_SCREENSHOTS_TO_REPO=1` のときだけここへ保存。それ以外は gitignore された検証用出力のみ。 */
const screenshotOutputDir =
  process.env.WRITE_DOC_SCREENSHOTS_TO_REPO === '1'
    ? repoDocsImagesDir
    : path.join(__dirname, '../test-results/doc-screenshots')

/** ドキュメント用 PNG の共通ピクセル寸法（`fullPage: false` のビューポートと一致） */
const DOC_SCREENSHOT_WIDTH = 1280
const DOC_SCREENSHOT_HEIGHT = 720

/**
 * ドキュメント用に主要タブの画面を PNG 保存する。
 * リポジトリの `docs/images` へ書き込むのは **`WRITE_DOC_SCREENSHOTS_TO_REPO=1` のときだけ**
 *（`capture_ui_screenshots.py` / `npm run screenshots*` が付与）。未設定時は `frontend/test-results/` のみ。
 * 再取得手順はリポジトリルートの `docs/development.md` を参照。
 *
 * 既定の取得先は既起動の API（例: localhost:8000）。`playwright.config` の webServer は
 * `--spawn-server` 付きで `capture_ui_screenshots.py` を実行したときのみ使う。
 * `npm run e2e` では `testIgnore` により本ファイルは実行されない（`E2E_RUN_SCREENSHOTS_SPEC=1` で解除）。
 */
test('主要画面のスクリーンショットを docs/images に保存', async ({ page }) => {
  mkdirSync(screenshotOutputDir, { recursive: true })

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
    path: path.join(screenshotOutputDir, 'summary.png'),
    fullPage: false,
  })

  await page.getByRole('button', { name: 'イベント' }).click()
  await expect(page.getByText(/全 \d+ 件/)).toBeVisible()
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'events.png'),
    fullPage: false,
  })

  const guideDetails = page.locator('td.event-type-guide-cell details.event-type-guide-details').first()
  await guideDetails.locator('summary').click()
  await expect(page.getByText('一般的な意味', { exact: true }).first()).toBeVisible()
  // ホバー／フォーカスで表示されるツールチップ用ポップオーバーは撮らない（details 展開のみ）
  await page.evaluate(() => {
    const a = document.activeElement
    if (a instanceof HTMLElement) a.blur()
  })
  await page.getByRole('heading', { name: 'vCenter Event Assistant' }).hover({ position: { x: 2, y: 2 } })
  await expect(page.locator('.event-type-guide-popover').first()).toBeHidden()
  await guideDetails.scrollIntoViewIfNeeded()
  await page.getByRole('heading', { name: 'vCenter Event Assistant' }).hover({ position: { x: 2, y: 2 } })
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'events-event-type-guide-expanded.png'),
    fullPage: false,
  })

  await page.getByRole('button', { name: 'グラフ' }).click()
  await expect(page.getByLabel('vCenter')).toBeVisible()
  await expect(page.getByLabel('メトリクスキー')).toBeVisible()
  // シード済みメトリクスで折れ線が描画されるまで待つ（空グラフのキャプチャを避ける）
  // Recharts は系列ごとに `.recharts-line` を複数描画するため strict 回避で先頭のみ検証する
  await expect(page.locator('.recharts-line').first()).toBeVisible({ timeout: 20_000 })
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'metrics.png'),
    fullPage: false,
  })

  await page.getByRole('button', { name: '設定' }).click()
  await page.getByRole('button', { name: '一般' }).click()
  await expect(page.getByLabel('外観')).toBeVisible()
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'settings-general.png'),
    fullPage: false,
  })

  await page.getByRole('button', { name: 'vCenter' }).click()
  await expect(page.getByRole('heading', { name: '登録' })).toBeVisible()
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'settings-vcenters.png'),
    fullPage: false,
  })

  await page.getByRole('button', { name: 'スコアルール' }).click()
  await expect(
    page.getByText(
      'イベント種別（event_type）ごとに、ルールベースのスコアへ加算する値を設定します。',
    ),
  ).toBeVisible()
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'settings-score-rules.png'),
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
    path: path.join(screenshotOutputDir, 'settings-event-type-guides-list.png'),
    fullPage: false,
  })

  await page.locator('nav.settings-subtabs').getByRole('button', { name: 'チャット' }).click()
  await expect(page.getByRole('heading', { name: 'プロンプトスニペット' })).toBeVisible()
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'settings-chat.png'),
    fullPage: false,
  })

  // チャット画面（ダミー履歴を注入）
  await page.evaluate(() => {
    const key = 'vea.chat_panel.v1'
    const dummyData = {
      messages: [
        {
          role: 'user',
          content: '最近のイベントの傾向を教えてください。',
          created_at: new Date(Date.now() - 3600000).toISOString(),
        },
        {
          role: 'assistant',
          content:
            '過去24時間で、`vim.event.ScreenshotDemoEvent` が 10 件発生しています。主な原因はシステムのメンテナンスによる一時的な負荷上昇です。詳細は「イベント」タブでフィルタリングして確認することをお勧めします。',
          created_at: new Date(Date.now() - 3590000).toISOString(),
          latency_ms: 1200,
          token_per_sec: 45.5,
        },
      ],
      rangeParts: {
        fromDate: '2026-04-12',
        fromTime: '07:00',
        toDate: '2026-04-13',
        toTime: '07:00',
      },
      vcenterId: '',
      includePeriodMetricsCpu: true,
      includePeriodMetricsMemory: false,
      includePeriodMetricsDiskIo: false,
      includePeriodMetricsNetworkIo: false,
      draft: '',
    }
    localStorage.setItem(key, JSON.stringify(dummyData))
  })
  await page.locator('nav.tabs').getByRole('button', { name: 'チャット' }).click()
  await expect(page.getByText('最近のイベントの傾向を教えてください。')).toBeVisible()
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'chat.png'),
    fullPage: false,
  })
})
