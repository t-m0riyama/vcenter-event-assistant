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

  it('API を呼ばない操作も、前回の報告から間が空いていればすぐに報告する', async () => {
    const m = await freshModule()
    const report = vi.fn(async () => m.activityHeaders())
    const off = m.setActivityReporter(report)
    // ページを開いたことは最初の要求で伝わったとする
    m.activityHeaders()
    vi.advanceTimersByTime(m.ACTIVITY_REPORT_INTERVAL_MS + 1)

    m.markUserActivity()
    m.markUserActivity() // 続けて操作してもまとめて 1 回
    vi.advanceTimersByTime(0)
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
    vi.advanceTimersByTime(0)
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
    vi.advanceTimersByTime(0)
    expect(report).not.toHaveBeenCalled()
    off()
  })

  it('登録を解除したら（ログアウト後）送らない', async () => {
    const m = await freshModule()
    const report = vi.fn(async () => m.activityHeaders())
    m.setActivityReporter(report)()
    vi.advanceTimersByTime(m.ACTIVITY_REPORT_INTERVAL_MS + 1)
    m.markUserActivity()
    vi.advanceTimersByTime(0)
    expect(report).not.toHaveBeenCalled()
  })

  it('操作が続いても報告を先延ばしにしない（最初の操作から決めた時点で送る）', async () => {
    const m = await freshModule()
    const report = vi.fn(async () => m.activityHeaders())
    const off = m.setActivityReporter(report)
    m.activityHeaders()
    vi.advanceTimersByTime(m.ACTIVITY_REPORT_INTERVAL_MS + 1)
    // 0.5 秒ごとに入力し続ける
    for (let t = 0; t < 10; t += 1) {
      m.markUserActivity()
      vi.advanceTimersByTime(500)
    }
    expect(report).toHaveBeenCalledTimes(1)
    off()
  })

  it('無操作期限の直前の操作は、待たずに期限より前に報告する（無操作 1 分・間隔 30 秒の設定）', async () => {
    const m = await freshModule()
    const report = vi.fn(async () => m.activityHeaders())
    const off = m.setActivityReporter(report, 30_000)
    m.activityHeaders() // T=0 にサーバへ伝わった
    vi.advanceTimersByTime(59_000)
    m.markUserActivity() // T=59s に API を呼ばない操作
    vi.advanceTimersByTime(0)
    expect(report).toHaveBeenCalledTimes(1) // T=60s の期限より前
    off()
  })

  it('応答に認証を通った印がなければ（429 や 502）、操作を未報告に戻す', async () => {
    const m = await freshModule()
    const fetchMock = vi.fn(async () => new Response('busy', { status: 429 }))
    vi.stubGlobal('fetch', fetchMock)
    try {
      m.markUserActivity()
      vi.advanceTimersByTime(m.USER_ACTIVITY_WINDOW_MS + 1)
      await m.fetchWithActivity('/api/config')
      // セッションは更新されていないので、次の要求もバックグラウンド扱いにしない
      expect(m.isUserIdle()).toBe(false)
      expect(m.activityHeaders()).toEqual({})

      m.markUserActivity()
      vi.advanceTimersByTime(m.USER_ACTIVITY_WINDOW_MS + 1)
      fetchMock.mockImplementation(
        async () => new Response('{}', { status: 200, headers: { 'X-VEA-Principal': 'id-alice:s1' } }),
      )
      await m.fetchWithActivity('/api/config')
      // 認証を通った応答なら伝わったものとして扱う
      expect(m.isUserIdle()).toBe(true)
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('送信中に予約済みの報告が終わっていても、伝わらなかった操作は改めて報告を予約する', async () => {
    const m = await freshModule()
    const report = vi.fn(async () => m.activityHeaders())
    const off = m.setActivityReporter(report, 30_000)
    vi.advanceTimersByTime(31_000)
    m.markUserActivity() // 報告を予約する（すぐ送る）
    const ticket = m.takeActivity() // その前に通常の要求が操作を伝えたつもりになる
    vi.advanceTimersByTime(0)
    expect(report).not.toHaveBeenCalled() // 予約済みの報告は「伝わった」とみなして送らない
    ticket.restore() // ところが要求は失敗した
    vi.advanceTimersByTime(m.RESTORED_REPORT_RETRY_MS - 1)
    expect(report).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(report).toHaveBeenCalledTimes(1)
    off()
  })

  it('無操作期限の直前に伝えられなかった操作は、期限より前に報告し直す（無操作 1 分・間隔 30 秒）', async () => {
    const m = await freshModule()
    const report = vi.fn(async () => m.activityHeaders())
    const off = m.setActivityReporter(report, 30_000)
    m.activityHeaders() // T=0 に伝えた（期限の目安は T=60 秒）
    vi.advanceTimersByTime(58_000)
    m.markUserActivity() // T=58 秒にクリック
    const ticket = m.takeActivity() // その要求は手前のプロキシの 502 で終わる
    vi.advanceTimersByTime(0)
    ticket.restore()
    vi.advanceTimersByTime(1_000) // 残り 2 秒の半分
    expect(report).toHaveBeenCalledTimes(1)
    off()
  })
})
