// 場面 diagnostics-settings: 設定の「診断」（概要、SSH の鍵と接続先、実行の対象の追加、コマンドの追加と 422）。
const section = (page, id) => page.locator(`section:has(h2#${id})`).first()

export async function shots(page, { base, save }) {
  await page.goto(`${base}/#/settings/diagnostics`)
  await page.getByRole('heading', { name: '追加のコマンド' }).waitFor()
  await page.waitForTimeout(800)
  await save('overview')

  const ssh = section(page, 'diagnostic-ssh-title')
  await ssh.locator('select').first().selectOption({ index: 1 })
  await ssh.getByText('管理者へ渡す公開鍵と登録依頼').click()
  await page.waitForTimeout(400)
  await save('ssh', ssh)

  const targets = section(page, 'diagnostic-targets-title')
  await targets.getByRole('button', { name: '実行の対象を追加' }).click()
  await targets.locator('select').first().selectOption({ label: 'mock-demo-vc' })
  const fetchHosts = targets.getByRole('button', { name: /ESXi 一覧を取得/ })
  if (await fetchHosts.count()) {
    await fetchHosts.click()
    await page.waitForTimeout(600)
  }
  await save('targets-form', targets)

  const commands = section(page, 'diagnostic-commands-title')
  await commands.getByRole('button', { name: 'コマンドを追加' }).click()
  await commands.getByLabel('名前').fill('ホスト名')
  await commands.getByLabel('コマンドの雛形').fill('hostname {{missing}}')
  await commands.getByRole('button', { name: '保存' }).click()
  await commands.getByRole('alert').waitFor()
  await page.waitForTimeout(300)
  await save('commands-422', commands)
}
