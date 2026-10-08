import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  apiDelete,
  apiGet,
  apiPatch,
  apiPost,
  FORBIDDEN_MESSAGE,
  onUnauthorized,
  PRINCIPAL_SWITCHED_MESSAGE,
  SESSION_EXPIRED_MESSAGE,
  setExpectedPrincipal,
} from './api'
import { markUserActivity, USER_ACTIVITY_WINDOW_MS } from './userActivity'

const GENERIC = 'リクエストに失敗しました。時間をおいて再度お試しください。'

/** 認証を通り、セッションの最終利用時刻を更新した応答。 */
function authedResponse(): Response {
  return new Response('{}', {
    status: 200,
    headers: { 'X-VEA-Principal': 'id-alice:s1', 'X-VEA-Session-Touched': '1' },
  })
}

describe('api', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.stubGlobal('fetch', vi.fn())
    // 既定は「利用者が操作した直後」（バックグラウンドの印なし）
    markUserActivity()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const fetchMock = () => globalThis.fetch as ReturnType<typeof vi.fn>

  it('apiGet returns parsed JSON on success', async () => {
    fetchMock().mockResolvedValueOnce(
      new Response(JSON.stringify({ x: 1 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    await expect(apiGet<{ x: number }>('/api/foo')).resolves.toEqual({ x: 1 })
  })

  it('apiGet throws generic Error for 5xx (no raw body leak)', async () => {
    fetchMock().mockResolvedValueOnce(new Response('body text', { status: 503 }))
    try {
      await apiGet('/api/foo')
      expect.unreachable()
    } catch (e) {
      expect(e).toBeInstanceOf(Error)
      expect((e as Error).message).toBe(GENERIC)
      expect((e as Error).message).not.toContain('body text')
    }
  })

  it('apiPost returns undefined on 204', async () => {
    fetchMock().mockResolvedValueOnce(new Response(null, { status: 204 }))
    await expect(apiPost('/api/foo', {})).resolves.toBeUndefined()
  })

  it('apiPost returns parsed JSON on 200', async () => {
    fetchMock().mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    await expect(apiPost<{ ok: boolean }>('/api/foo', { a: 1 })).resolves.toEqual({ ok: true })
  })

  it('apiPost sends X-Requested-With on mutations', async () => {
    fetchMock().mockResolvedValueOnce(new Response(null, { status: 204 }))
    await apiPost('/api/foo', { a: 1 })
    const init = fetchMock().mock.calls[0]?.[1] as RequestInit
    const h = new Headers(init.headers)
    expect(h.get('X-Requested-With')).toBe('XMLHttpRequest')
  })

  it('apiPost throws generic Error for 400', async () => {
    fetchMock().mockResolvedValueOnce(new Response('nope', { status: 400 }))
    try {
      await apiPost('/api/foo', {})
      expect.unreachable()
    } catch (e) {
      expect((e as Error).message).toBe(GENERIC)
      expect((e as Error).message).not.toContain('nope')
    }
  })

  it('apiPatch returns parsed JSON on success', async () => {
    fetchMock().mockResolvedValueOnce(
      new Response(JSON.stringify({ patched: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    await expect(apiPatch<{ patched: boolean }>('/api/foo', { x: 1 })).resolves.toEqual({
      patched: true,
    })
  })

  it('apiPatch surfaces 409 conflict body exactly', async () => {
    fetchMock().mockResolvedValueOnce(new Response('bad', { status: 409 }))
    try {
      await apiPatch('/api/foo', {})
      expect.unreachable()
    } catch (e) {
      expect((e as Error).message).toBe('bad')
    }
  })

  it('apiPost surfaces 422 validation body exactly', async () => {
    fetchMock().mockResolvedValueOnce(new Response('field required', { status: 422 }))
    try {
      await apiPost('/api/foo', {})
      expect.unreachable()
    } catch (e) {
      expect((e as Error).message).toBe('field required')
    }
  })

  it('apiPost uses generic message when 422 body is empty', async () => {
    fetchMock().mockResolvedValueOnce(new Response('', { status: 422 }))
    try {
      await apiPost('/api/foo', {})
      expect.unreachable()
    } catch (e) {
      expect((e as Error).message).toBe(GENERIC)
    }
  })

  it('apiDelete resolves on success', async () => {
    fetchMock().mockResolvedValueOnce(new Response(null, { status: 204 }))
    await expect(apiDelete('/api/foo')).resolves.toBeUndefined()
  })

  it('apiDelete throws generic Error for 5xx', async () => {
    fetchMock().mockResolvedValueOnce(new Response('gone', { status: 500 }))
    try {
      await apiDelete('/api/foo')
      expect.unreachable()
    } catch (e) {
      expect((e as Error).message).toBe(GENERIC)
      expect((e as Error).message).not.toContain('gone')
    }
  })

  it('401 はセッション切れとして通知し、案内の文言で失敗する', async () => {
    const listener = vi.fn()
    const off = onUnauthorized(listener)
    try {
      fetchMock().mockResolvedValueOnce(new Response('{"detail":"x"}', { status: 401 }))
      await expect(apiGet('/api/foo')).rejects.toThrow(SESSION_EXPIRED_MESSAGE)
      expect(listener).toHaveBeenCalledTimes(1)
    } finally {
      off()
    }
    // 登録を解除したあとは呼ばれない
    fetchMock().mockResolvedValueOnce(new Response('{"detail":"x"}', { status: 401 }))
    await expect(apiGet('/api/foo')).rejects.toThrow(SESSION_EXPIRED_MESSAGE)
    expect(listener).toHaveBeenCalledTimes(1)
  })

  it('403 は権限エラーの文言で失敗する', async () => {
    const listener = vi.fn()
    const off = onUnauthorized(listener)
    try {
      fetchMock().mockResolvedValueOnce(new Response('{"detail":"x"}', { status: 403 }))
      await expect(apiDelete('/api/foo')).rejects.toThrow(FORBIDDEN_MESSAGE)
      expect(listener).not.toHaveBeenCalled()
    } finally {
      off()
    }
  })

  it('利用者が操作していないときの要求には X-VEA-Background を付ける', async () => {
    const bg = (i: number) =>
      new Headers((fetchMock().mock.calls[i]?.[1] as RequestInit).headers).get('X-VEA-Background')
    const now = Date.now()
    // 古い操作は 1 回目の要求で伝わる（バックグラウンド扱いにしない）
    markUserActivity(now - USER_ACTIVITY_WINDOW_MS - 1)
    fetchMock().mockImplementation(() => Promise.resolve(authedResponse()))
    await apiGet('/api/foo')
    expect(bg(0)).toBeNull()
    // 以後、操作がないまま出る要求はバックグラウンド
    await apiGet('/api/foo')
    expect(bg(1)).toBe('1')

    // 操作の直後の要求は通常扱い
    markUserActivity(now)
    await apiGet('/api/foo')
    expect(bg(2)).toBeNull()
  })

  it('定期取得の間隔より前の操作も、次の要求で必ず伝わる', async () => {
    const bg = (i: number) =>
      new Headers((fetchMock().mock.calls[i]?.[1] as RequestInit).headers).get('X-VEA-Background')
    fetchMock().mockImplementation(() => Promise.resolve(authedResponse()))
    const now = Date.now()
    markUserActivity(now - 120_000)
    await apiGet('/api/foo') // 未報告の操作を伝える
    expect(bg(0)).toBeNull()
    // 定期取得の 40 秒前にスクロールした（API は呼んでいない）
    markUserActivity(now - 40_000)
    await apiGet('/api/foo')
    expect(bg(1)).toBeNull()
  })

  it('クリックやキー入力を利用者の操作として記録する', async () => {
    markUserActivity(Date.now() - USER_ACTIVITY_WINDOW_MS - 1)
    fetchMock().mockResolvedValueOnce(new Response('{}', { status: 200 }))
    await apiGet('/api/foo') // 古い操作を報告済みにする
    fetchMock().mockClear()
    window.dispatchEvent(new Event('keydown'))
    fetchMock().mockResolvedValueOnce(new Response('{}', { status: 200 }))
    await apiGet('/api/foo')
    expect(new Headers((fetchMock().mock.calls[0]?.[1] as RequestInit).headers).get('X-VEA-Background')).toBeNull()
  })

  it('通信エラーで届かなかった要求の操作は、次の要求で改めて伝える', async () => {
    const bg = (i: number) =>
      new Headers((fetchMock().mock.calls[i]?.[1] as RequestInit).headers).get('X-VEA-Background')
    // 判定窓より前の、まだ伝えていない操作
    markUserActivity(Date.now() - USER_ACTIVITY_WINDOW_MS - 1)
    fetchMock().mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await expect(apiGet('/api/foo')).rejects.toThrow('Failed to fetch')
    expect(bg(0)).toBeNull()

    fetchMock().mockImplementation(() => Promise.resolve(authedResponse()))
    await apiGet('/api/foo')
    expect(bg(1)).toBeNull() // 届かなかった操作をここで伝える
    await apiGet('/api/foo')
    expect(bg(2)).toBe('1')
  })

  it('表示中の利用者と違う利用者の応答は、要求した画面に渡さない', async () => {
    fetchMock().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ secret: 'bob' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json', 'X-VEA-Principal': 'id-bob:s1' },
        }),
      ),
    )
    setExpectedPrincipal('id-alice:s1')
    try {
      await expect(apiGet('/api/foo')).rejects.toThrow(PRINCIPAL_SWITCHED_MESSAGE)
      setExpectedPrincipal('id-bob:s1')
      await expect(apiGet('/api/foo')).resolves.toEqual({ secret: 'bob' })
    } finally {
      setExpectedPrincipal(null)
    }
  })

  it('表示中の利用者を要求に付けて送る（サーバが Cookie の利用者と照合する）', async () => {
    fetchMock().mockImplementation(() => Promise.resolve(new Response(null, { status: 204 })))
    setExpectedPrincipal('id-alice:s1')
    try {
      await apiPost('/api/foo', {})
      const h = new Headers((fetchMock().mock.calls[0]?.[1] as RequestInit).headers)
      expect(h.get('X-VEA-Expected-Principal')).toBe('id-alice:s1')
      expect(h.get('X-Requested-With')).toBe('XMLHttpRequest')
    } finally {
      setExpectedPrincipal(null)
    }
    await apiPost('/api/foo', {})
    const h = new Headers((fetchMock().mock.calls[1]?.[1] as RequestInit).headers)
    expect(h.get('X-VEA-Expected-Principal')).toBeNull()
  })
})
