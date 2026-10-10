import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test, type Page } from '@playwright/test'
import { isAuthEnabled } from './credentials'

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
 * タブ下線の scaleX アニメ（App.css で 0.2s）と :focus-visible リングを撮らないよう落ち着かせる。
 */
async function settleTabChrome(page: Page): Promise<void> {
  await page.evaluate(() => {
    const a = document.activeElement
    if (a instanceof HTMLElement) a.blur()
  })
  await page.getByRole('heading', { name: 'vCenter Event Assistant' }).hover({
    position: { x: 2, y: 2 },
  })
  // CSS transition 完了を待つ（reduced-motion 時も短い固定待ちで害はない）
  await page.waitForTimeout(250)
}

async function openMainTab(page: Page, name: string): Promise<void> {
  const tab = page.locator('nav.tabs').getByRole('button', { name, exact: true })
  await tab.click()
  await expect(tab).toHaveClass(/active/)
  await settleTabChrome(page)
}

async function openSettingsSubTab(page: Page, name: string): Promise<void> {
  const tab = page
    .locator('nav.settings-subtabs')
    .getByRole('button', { name, exact: true })
  await tab.click()
  await expect(tab).toHaveClass(/active/)
  await settleTabChrome(page)
}

/**
 * ドキュメント用に主要タブの画面を PNG 保存する。
 * リポジトリの `docs/images` へ書き込むのは **`WRITE_DOC_SCREENSHOTS_TO_REPO=1` のときだけ**
 *（`capture_ui_screenshots.py` / `npm run screenshots*` が付与）。未設定時は `frontend/test-results/` のみ。
 * 再取得手順はリポジトリルートの `docs/development/development.md` を参照。
 *
 * 既定の取得先は既起動の API（例: localhost:8000）。`playwright.config` の webServer は
 * `--spawn-server` 付きで `capture_ui_screenshots.py` を実行したときのみ使う。
 * `npm run e2e` では `testIgnore` により本ファイルは実行されない（`E2E_RUN_SCREENSHOTS_SPEC=1` で解除）。
 */

/** ログイン画面は未ログイン状態で撮る（chromium プロジェクトの storageState を使わない）。 */
test.describe('ログイン画面', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('ログイン画面を docs/images に保存', async ({ page, request }) => {
    test.skip(!(await isAuthEnabled(request)), 'VEA_AUTH_ENABLED=false のサーバー')
    mkdirSync(screenshotOutputDir, { recursive: true })
    await page.setViewportSize({
      width: DOC_SCREENSHOT_WIDTH,
      height: DOC_SCREENSHOT_HEIGHT,
    })
    await page.goto('/')
    await expect(page.getByRole('form', { name: 'ログイン' })).toBeVisible()
    await expect(page.getByLabel('ユーザー名')).toBeVisible()
    await expect(page.getByLabel('パスワード')).toBeVisible()
    // 資格情報は画像に残さない（空の入力欄のまま）
    await page.screenshot({
      path: path.join(screenshotOutputDir, 'login.png'),
      fullPage: false,
    })
  })
})

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

  await openMainTab(page, '概要')
  await expect(page.getByText('登録 vCenter', { exact: true })).toBeVisible()
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'summary.png'),
    fullPage: false,
  })

  await openMainTab(page, 'イベント')
  const eventsPanel = page.locator('.panel:visible')
  await expect(eventsPanel.getByText(/全 \d+ 件/).first()).toBeVisible()
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'events.png'),
    fullPage: false,
  })

  // 概要タブなど hidden なパネル内の同名要素を拾わないよう、表示中の要素に限定する
  const guideDetails = page
    .locator('td.event-type-guide-cell details.event-type-guide-details:visible')
    .first()
  await guideDetails.locator('summary').click()
  await expect(guideDetails.getByText('一般的な意味', { exact: true })).toBeVisible()
  // ホバー／フォーカスで表示されるツールチップ用ポップオーバーは撮らない（details 展開のみ）
  await settleTabChrome(page)
  await expect(page.locator('.event-type-guide-popover').first()).toBeHidden()
  await guideDetails.scrollIntoViewIfNeeded()
  await settleTabChrome(page)
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'events-event-type-guide-expanded.png'),
    fullPage: false,
  })

  await openMainTab(page, 'ログ')
  await expect(page.getByLabel('ログの操作')).toBeVisible()
  await expect(page.getByText('条件に一致するログはありません')).toBeVisible()
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'logs.png'),
    fullPage: false,
  })

  await openMainTab(page, 'グラフ')
  // ログタブなど hidden パネル内の同名ラベルを拾わない
  const metricsPanel = page.locator('.panel:visible')
  await expect(metricsPanel.getByLabel('メトリクスキー')).toBeVisible()
  await expect(metricsPanel.getByLabel('vCenter')).toBeVisible()
  // シード済みメトリクスで折れ線が描画されるまで待つ（空グラフのキャプチャを避ける）
  // Recharts は系列ごとに `.recharts-line` を複数描画するため strict 回避で先頭のみ検証する
  // 単一系列はエリア（.recharts-area）で描画されるため両方を待つ
  await expect(page.locator('.recharts-line, .recharts-area').first()).toBeVisible({
    timeout: 20_000,
  })
  await settleTabChrome(page)
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'metrics.png'),
    fullPage: false,
  })

  await openMainTab(page, 'ダイジェスト')
  const digestsPanel = page.locator('.panel:visible')
  await expect(digestsPanel.getByRole('button', { name: '一覧を更新' })).toBeVisible()
  await expect(digestsPanel.locator('.digests-count-hint')).toHaveText(/全 \d+ 件/)
  await digestsPanel
    .getByRole('navigation', { name: 'ダイジェスト一覧' })
    .getByRole('button')
    .first()
    .click()
  await expect(digestsPanel.getByRole('heading', { name: '日次ダイジェスト（デモ）' })).toBeVisible()
  await settleTabChrome(page)
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'digests.png'),
    fullPage: false,
  })

  await openMainTab(page, '通知履歴')
  const alertsHistoryPanel = page.locator('.panel:visible')
  await expect(alertsHistoryPanel.getByRole('button', { name: '一覧を更新' })).toBeVisible()
  await expect(alertsHistoryPanel.getByText('デモ: イベントスコア')).toBeVisible()
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'alerts-history.png'),
    fullPage: false,
  })

  await openMainTab(page, '設定')
  await openSettingsSubTab(page, '一般')
  await expect(page.getByLabel('外観')).toBeVisible()
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'settings-general.png'),
    fullPage: false,
  })

  await openSettingsSubTab(page, 'vCenter')
  await expect(page.getByRole('heading', { name: '登録' })).toBeVisible()
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'settings-vcenters.png'),
    fullPage: false,
  })

  await openSettingsSubTab(page, 'スコアルール')
  await expect(
    page.getByText('ルールベースのスコアへ加算する値をサーバーに保存します', {
      exact: false,
    }),
  ).toBeVisible()
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'settings-score-rules.png'),
    fullPage: false,
  })

  await openSettingsSubTab(page, 'イベント種別ガイド')
  await expect(
    page.getByText(
      'イベント種別（event_type。収集したイベントの種別文字列と完全に一致するもの）ごとに',
      { exact: false },
    ),
  ).toBeVisible()
  await page.locator('.event-type-guides-list').scrollIntoViewIfNeeded()
  await settleTabChrome(page)
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'settings-event-type-guides-list.png'),
    fullPage: false,
  })

  await openSettingsSubTab(page, 'アラート')
  await expect(
    page.getByText('判定の対象となるのは、有効にしたルールのみです', { exact: false }),
  ).toBeVisible()
  await expect(page.getByText('デモ: イベントスコア').first()).toBeVisible()
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'settings-alerts.png'),
    fullPage: false,
  })

  await openSettingsSubTab(page, 'プラグイン')
  await expect(page.getByText(/レジストリ世代/)).toBeVisible()
  await expect(page.getByText('組み込み').first()).toBeVisible()
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'settings-plugins.png'),
    fullPage: false,
  })

  await openSettingsSubTab(page, 'チャット')
  await expect(page.getByRole('heading', { name: 'エクスポート・インポート' })).toBeVisible()
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'settings-chat.png'),
    fullPage: false,
  })

  // チャット画面（ダミー履歴を sessionStorage に注入。キーは chatPanelStorage と同一）
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
      rollingDurationMs: null,
      vcenterId: '',
      includePeriodMetricsCpu: true,
      includePeriodMetricsMemory: false,
      includePeriodMetricsDiskIo: false,
      includePeriodMetricsNetworkIo: false,
      draft: '',
    }
    sessionStorage.setItem(key, JSON.stringify(dummyData))
  })
  await openMainTab(page, 'チャット')
  await expect(page.getByText('最近のイベントの傾向を教えてください。')).toBeVisible()
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'chat.png'),
    fullPage: false,
  })

  await openMainTab(page, 'タイムライン')
  await expect(page.getByRole('button', { name: 'タイムラインを生成' })).toBeVisible()
  await page.screenshot({
    path: path.join(screenshotOutputDir, 'timeline.png'),
    fullPage: false,
  })
})
