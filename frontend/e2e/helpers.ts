import { expect, type Page } from '@playwright/test'

/**
 * アプリ共通のエラーバナー（`role="alert"`）が表示されていないことを検証する。
 */
export async function expectNoErrorBanner(page: Page): Promise<void> {
  await expect(page.locator('[role="alert"]')).toHaveCount(0)
}

/**
 * アプリ共通のエラーバナー（`role="alert"`）が 1 件表示され、そのテキストに `substring` を含むことを検証する。
 */
export async function expectErrorBanner(
  page: Page,
  substring: string,
): Promise<void> {
  const alert = page.locator('[role="alert"]')
  await expect(alert).toHaveCount(1)
  await expect(alert).toContainText(substring)
}
