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

  it('直前に報告していれば、次の間隔まで送らない', async () => {
    const m = await freshModule()
    const report = vi.fn(async () => m.activityHeaders())
    const off = m.setActivityReporter(report)
    m.activityHeaders() // たった今、通常の要求で伝えた
    m.markUserActivity()
    vi.advanceTimersByTime(m.ACTIVITY_REPORT_DEBOUNCE_MS * 2)
    expect(report).not.toHaveBeenCalled()
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
