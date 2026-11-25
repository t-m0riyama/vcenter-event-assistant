// 場面 incident-diagnostics: インシデントの対応手順、実行のダイアログ（プレビュー後）、診断の結果、経過。
const INCIDENT = 'デモ: 診断コマンドで NIC を調査'
const block = (page, name) => page.getByRole('heading', { name, level: 3 }).locator('xpath=..')

export async function shots(page, { base, save }) {
  await page.goto(`${base}/#/incidents`)
  await page.getByText(INCIDENT).first().click()
  await page.getByRole('heading', { name: '対応手順', level: 3 }).waitFor()
  await page.getByText('NIC の統計').first().waitFor()
  await page.waitForTimeout(800)
  await save('detail')
  await save('procedures', block(page, '対応手順'))

  const card = page.locator('li, div').filter({ hasText: 'NIC の統計' }).filter({ has: page.getByRole('button', { name: '実行' }) }).last()
  await card.getByRole('button', { name: '実行' }).first().click()
  const dialog = page.getByRole('dialog')
  await dialog.waitFor()
  await dialog.getByRole('textbox').first().fill('vmnic0')
  await dialog.getByRole('button', { name: 'プレビュー' }).click()
  await dialog.getByText('demo-diagnostics').first().waitFor()
  await page.waitForTimeout(300)
  await save('run-dialog', dialog)
  await dialog.getByRole('button', { name: '閉じる' }).first().click()

  const results = block(page, '診断の結果')
  await results.locator('summary').filter({ hasText: 'NIC の統計' }).first().click()
  await results.locator('.incident-diagnostic-output').nth(1).waitFor()
  await page.waitForTimeout(500)
  await save('results', results)
}
