import { expect, type Page } from '@playwright/test'

/**
 * アプリ共通のエラーバナー（`role="alert"`）が表示されていないことを検証する。
 */
export async function expectNoErrorBanner(page: Page): Promise<void> {
  await expect(page.locator('[role="alert"]')).toHaveCount(0)
}
