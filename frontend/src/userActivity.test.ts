/**
 * @vitest-environment happy-dom
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

type ActivityModule = typeof import('./userActivity')

async function freshModule(): Promise<ActivityModule> {
  vi.resetModules()
  return import('./userActivity')
}

describe('userActivity の操作報告', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('API を呼ばない操作も、前回の報告から間が空いていれば少し待って報告する', async () => {
    const m = await freshModule()
    const report = vi.fn(async () => m.activityHeaders())
    const off = m.setActivityReporter(report)
    // ページを開いたことは最初の要求で伝わったとする
    m.activityHeaders()
    vi.advanceTimersByTime(m.ACTIVITY_REPORT_INTERVAL_MS + 1)

    m.markUserActivity()
    m.markUserActivity() // 続けて操作してもまとめて 1 回
    expect(report).not.toHaveBeenCalled()
    vi.advanceTimersByTime(m.ACTIVITY_REPORT_DEBOUNCE_MS)
    expect(report).toHaveBeenCalledTimes(1)
    // 報告はバックグラウンド扱いにならない
    expect(await report.mock.results[0].value).toEqual({})
    off()
  })

  it('直前に報告していれば、次の間隔が来た時点で送る（操作は捨てない）', async () => {
    const m = await freshModule()
    const report = vi.fn(async () => m.activityHeaders())
    const off = m.setActivityReporter(report, 30_000)
    m.activityHeaders() // たった今、通常の要求で伝えた
    vi.advanceTimersByTime(1_000)
    m.markUserActivity()
    vi.advanceTimersByTime(28_000)
    expect(report).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1_000)
    expect(report).toHaveBeenCalledTimes(1)
    off()
  })

  it('サーバが返した短い間隔（無操作 1 分の設定なら 30 秒）で報告する', async () => {
    const m = await freshModule()
    const report = vi.fn(async () => m.activityHeaders())
    const off = m.setActivityReporter(report, 30_000)
    m.activityHeaders()
    vi.advanceTimersByTime(31_000)
    m.markUserActivity()
    vi.advanceTimersByTime(m.ACTIVITY_REPORT_DEBOUNCE_MS)
    expect(report).toHaveBeenCalledTimes(1)
    off()
  })

  it('報告に失敗したら未報告に戻し、次の要求で伝える', async () => {
    const m = await freshModule()
    const report = vi.fn(async () => {
      m.activityHeaders()
      throw new Error('network')
    })
    const off = m.setActivityReporter(report)
    m.activityHeaders()
    vi.advanceTimersByTime(m.ACTIVITY_REPORT_INTERVAL_MS + 1)
    m.markUserActivity()
    // 判定窓を過ぎてから報告が失敗した状況にする
    vi.advanceTimersByTime(m.USER_ACTIVITY_WINDOW_MS + 1)
    expect(report).toHaveBeenCalledTimes(1)
    await Promise.resolve()
    await Promise.resolve()
    // 失敗した報告の操作は、次の（定期取得の）要求で伝わる
    expect(m.activityHeaders()).toEqual({})
    off()
  })

  it('待っている間に別の要求で伝わったら送らない', async () => {
    const m = await freshModule()
    const report = vi.fn(async () => m.activityHeaders())
    const off = m.setActivityReporter(report)
    m.activityHeaders()
    vi.advanceTimersByTime(m.ACTIVITY_REPORT_INTERVAL_MS + 1)
    m.markUserActivity()
    m.activityHeaders() // 利用者の操作で API を呼んだ
    vi.advanceTimersByTime(m.ACTIVITY_REPORT_DEBOUNCE_MS)
    expect(report).not.toHaveBeenCalled()
    off()
  })

  it('登録を解除したら（ログアウト後）送らない', async () => {
    const m = await freshModule()
    const report = vi.fn(async () => m.activityHeaders())
    m.setActivityReporter(report)()
    vi.advanceTimersByTime(m.ACTIVITY_REPORT_INTERVAL_MS + 1)
    m.markUserActivity()
    vi.advanceTimersByTime(m.ACTIVITY_REPORT_DEBOUNCE_MS)
    expect(report).not.toHaveBeenCalled()
  })
})
