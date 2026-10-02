import { readFile } from 'node:fs/promises'
import { expect, test } from '@playwright/test'

test('hands CSV to the browser with one export request and no paginated JSON fetches', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('vea.displayTimeZone', 'Asia/Tokyo'))
  // Only the list is mocked; the native download reaches the real CSV endpoint.
  let listRequests = 0
  await page.route('**/api/logs?*', async (route) => {
    listRequests += 1
    await route.fulfill({ json: { items: [], total: 2_000_000 } })
  })
  let downloads = 0
  page.on('download', () => { downloads += 1 })
  await page.goto('/#/logs')
  const button = page.getByRole('button', { name: 'CSVをダウンロード' })
  await expect(button).toBeEnabled()
  const before = listRequests
  const downloadPromise = page.waitForEvent('download')
  await button.click()
  const download = await downloadPromise
  expect(await download.failure()).toBeNull()
  expect(download.suggestedFilename()).toMatch(/^logs-\d{8}-\d{6}\.csv$/)
  const path = await download.path()
  expect(path).not.toBeNull()
  const bytes = await readFile(path!)
  expect([...bytes.subarray(0, 3)]).toEqual([0xef, 0xbb, 0xbf])
  expect(bytes.toString('utf8')).toContain('byte_offset,time_zone,utc_offset\r\n')
  expect(downloads).toBe(1)
  expect(new URL(download.url()).searchParams.get('time_zone')).toBe('Asia/Tokyo')
  expect(listRequests).toBe(before)
  await expect(page.getByText(/ダウンロードを開始しました/)).toBeVisible()
  expect(page.url()).toContain('#/logs')
})
