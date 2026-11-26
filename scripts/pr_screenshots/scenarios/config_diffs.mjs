// 場面 config-diffs: タイムラインの「構成の差分」の欄、構成変更のカードの差分、設定の vCenter の読み取りの状態。
const VCENTER = 'screenshot-e2e-vc'

async function vcenterId(page, base) {
  const response = await page.request.get(`${base}/api/vcenters`)
  const body = await response.json()
  const rows = Array.isArray(body) ? body : body.items
  return rows.find((row) => row.name === VCENTER).id
}

const section = (page, name) => page.locator('section').filter({ has: page.getByRole('heading', { name, level: 3, exact: true }) }).first()

export async function shots(page, { base, save }) {
  await page.goto(`${base}/#/timeline?range=6h`)
  await page.waitForTimeout(500)
  const id = await vcenterId(page, base)

  // VM: カードに添った差分と、対象の欄（入れ替わりの無い通常の差分）。
  await page.goto(`${base}/#/timeline?range=6h&vcenter_id=${id}&entity=demo-vm-01&entity_moid=vm-9001`)
  const diffs = section(page, '構成の差分')
  await diffs.waitFor()
  await diffs.getByText(/CPU/).first().waitFor()
  await page.waitForTimeout(800)
  await save('vm-section', diffs)
  const highlights = page.locator('section[aria-label="ハイライト"]').first()
  const card = highlights.locator('section.timeline-highlights__card').filter({ has: page.getByRole('heading', { name: '構成変更', level: 4 }) }).first()
  // 固定のヘッダーに上端が隠れないよう、カードを画面の中ほどに置いてから撮る。
  await card.evaluate((element) => element.scrollIntoView({ block: 'center' }))
  await page.waitForTimeout(300)
  await save('vm-card', card)

  // ホスト: イベントの無い VLAN の変更（対象の欄でだけ見える）。
  await page.goto(`${base}/#/timeline?range=6h&vcenter_id=${id}&entity=demo-esxi-01&entity_moid=host-9001`)
  const hostDiffs = section(page, '構成の差分')
  await hostDiffs.waitFor()
  await hostDiffs.getByText(/VLAN/).first().waitFor()
  const toggle = hostDiffs.locator('summary').first()
  if (await toggle.count()) await toggle.click()
  await page.waitForTimeout(600)
  await save('host-section', hostDiffs)

  // 設定の vCenter: 関係の収集と構成の読み取りの状態。
  await page.goto(`${base}/#/settings/vcenters`)
  await page.getByRole('columnheader', { name: '関係の収集' }).waitFor()
  await page.getByText(VCENTER).first().waitFor()
  await page.waitForTimeout(800)
  await save('vcenters', page.locator('table:has(th:has-text("関係の収集"))').first())
}
