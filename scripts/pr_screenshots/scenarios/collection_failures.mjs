// 場面 collection-failures: 設定の vCenter の「関係の収集」と、プラグインの「vCenter 別の実行状況」。
export async function shots(page, { base, save }) {
  await page.goto(`${base}/#/settings/vcenters`)
  await page.getByRole('columnheader', { name: '関係の収集' }).waitFor()
  await page.getByText('lab-vc-02').first().waitFor()
  await page.waitForTimeout(800)
  const table = page.locator('table:has(th:has-text("関係の収集"))').first()
  await save('vcenters', table)

  // 詳細を開いた状態（元の記録の文字列）。
  const details = table.locator('details').first()
  if (await details.count()) {
    await details.locator('summary').click()
    await page.waitForTimeout(300)
    await save('vcenters-details', table)
  }

  await page.goto(`${base}/#/settings/plugins`)
  const expand = page.locator('tr:has-text("builtin.vcenter.events")').getByRole('button', { name: /の詳細を開く/ }).first()
  await expand.waitFor()
  await expand.click()
  const runs = page.locator('h3:has-text("vCenter 別の実行状況") + *').first()
  await runs.waitFor()
  await page.waitForTimeout(600)
  await save('plugin-runs', runs)
}
