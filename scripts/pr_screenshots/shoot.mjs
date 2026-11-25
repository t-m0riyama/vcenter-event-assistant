// run.py から呼ばれ、場面（scenarios/<名前>.mjs）の shots を明暗の両テーマで実行する。
// 使い方: node shoot.mjs <base URL> <出力ディレクトリ> <場面>
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const require = createRequire(path.join(here, '..', '..', 'frontend', 'package.json'))
const { chromium } = require('@playwright/test')

const [, , base, out, scenario] = process.argv
const { shots } = await import(pathToFileURL(path.join(here, 'scenarios', `${scenario.replaceAll('-', '_')}.mjs`)).href)

const browser = await chromium.launch()
try {
  for (const theme of ['light', 'dark']) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1 })
    await context.addInitScript((value) => localStorage.setItem('vea.theme', value), theme)
    const page = await context.newPage()
    await page.goto(`${base}/`)
    await page.getByLabel('ユーザー名').fill(process.env.VEA_DEMO_USERNAME)
    await page.getByLabel('パスワード').fill(process.env.VEA_DEMO_PASSWORD)
    await page.getByRole('button', { name: 'ログイン' }).click()
    await page.getByRole('button', { name: /アカウントメニュー/ }).waitFor()
    await shots(page, {
      base,
      theme,
      /** `<テーマ>-<名前>.png` を書き出す。target を渡すとその要素だけを撮る。 */
      save: (name, target) =>
        (target ?? page).screenshot({ path: path.join(out, `${theme}-${name}.png`), ...(target ? {} : { fullPage: true }) }),
    })
    await context.close()
  }
} finally {
  await browser.close()
}
