import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  apiDelete,
  apiFetchBlob,
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

  describe('apiFetchBlob', () => {
    it('応答のファイル名と Blob を返し、POST に変更系のヘッダと中断のシグナルを付ける', async () => {
      fetchMock().mockResolvedValueOnce(new Response('# 調査資料', {
        headers: {
          'Content-Disposition': 'attachment; filename="timeline-20261124-120000.md"',
          'Content-Type': 'text/markdown; charset=utf-8',
        },
      }))
      const signal = new AbortController().signal
      const body = { from: '2026-11-24T03:00:00Z', to: '2026-11-24T04:00:00Z' }
      const file = await apiFetchBlob('/api/export', { method: 'POST', body, signal })
      expect(file.filename).toBe('timeline-20261124-120000.md')
      expect(file.blob.type).toBe('text/markdown; charset=utf-8')
      expect(await file.blob.text()).toBe('# 調査資料')
      const [url, init] = fetchMock().mock.calls[0] as [string, RequestInit]
      expect(url).toBe('/api/export')
      expect(init).toMatchObject({ method: 'POST', body: JSON.stringify(body), signal })
      const headers = new Headers(init.headers)
      expect(headers.get('X-Requested-With')).toBe('XMLHttpRequest')
      expect(headers.get('Content-Type')).toBe('application/json')
    })

    it.each([
      ['期間を短くしてください', '期間を短くしてください'],
      [[{ loc: ['body', 'from'], msg: '必須です' }, { loc: ['query', 'time_zone'], msg: '無効です' }], 'from: 必須です / query.time_zone: 無効です'],
    ])('422 の detail を表示用に返す（%j）', async (detail, message) => {
      fetchMock().mockResolvedValueOnce(Response.json({ detail }, { status: 422 }))
      await expect(apiFetchBlob('/api/export')).rejects.toMatchObject({ status: 422, message })
    })

    it.each([
      [null, null],
      ["attachment; filename*=UTF-8''%E8%AA%BF%E6%9F%BB.md", '調査.md'],
      ["attachment; filename=report.md; filename*=utf-8'ja'%E8%AA%BF%E6%9F%BB.md", '調査.md'],
      ['attachment; filename="report\\"draft;1.md"', 'report"draft;1.md'],
      ["attachment; filename*=UTF-8''%FF; filename=report.md", 'report.md'],
    ])('添付名を読む（%s）', async (disposition, filename) => {
      fetchMock().mockResolvedValueOnce(new Response('report', {
        headers: disposition === null ? {} : { 'Content-Disposition': disposition },
      }))
      await expect(apiFetchBlob('/api/export')).resolves.toMatchObject({ filename })
    })

    it('401 で認証ゲートへ通知する', async () => {
      const listener = vi.fn()
      const unsubscribe = onUnauthorized(listener)
      try {
        fetchMock().mockResolvedValueOnce(new Response(null, { status: 401 }))
        await expect(apiFetchBlob('/api/export')).rejects.toMatchObject({ status: 401, message: SESSION_EXPIRED_MESSAGE })
        expect(listener).toHaveBeenCalledTimes(1)
      } finally {
        unsubscribe()
      }
    })

    it('400 の detail を返す', async () => {
      const detail = '終了は開始より後にしてください。'
      fetchMock().mockResolvedValueOnce(Response.json({ detail }, { status: 400 }))
      await expect(apiFetchBlob('/api/export')).rejects.toMatchObject({ status: 400, message: detail })
    })

    it.each([
      [null, 3000],
      ['60', 10_000],
    ])('503 後に %s の Retry-After に応じて待ち、成功したファイルを返す', async (retryAfter, waitMs) => {
      vi.useFakeTimers()
      try {
        fetchMock()
          .mockResolvedValueOnce(new Response(null, {
            status: 503,
            headers: retryAfter === null ? {} : { 'Retry-After': retryAfter },
          }))
          .mockResolvedValueOnce(new Response('report', {
            headers: { 'Content-Disposition': 'attachment; filename=report.md' },
          }))
        const result = apiFetchBlob('/api/export')
        await vi.advanceTimersByTimeAsync(waitMs - 1)
        expect(fetchMock()).toHaveBeenCalledTimes(1)
        await vi.advanceTimersByTimeAsync(1)
        await expect(result).resolves.toMatchObject({ filename: 'report.md' })
        expect(fetchMock()).toHaveBeenCalledTimes(2)
      } finally {
        vi.useRealTimers()
      }
    })

    it('503 は Retry-After に従って 1 回だけ再試行する', async () => {
      vi.useFakeTimers()
      try {
        fetchMock().mockImplementation(() => new Response('', { status: 503, headers: { 'Retry-After': '2' } }))
        const result = expect(apiFetchBlob('/api/export')).rejects.toMatchObject({ status: 503 })
        await vi.advanceTimersByTimeAsync(1999)
        expect(fetchMock()).toHaveBeenCalledTimes(1)
        await vi.advanceTimersByTimeAsync(1)
        await result
        expect(fetchMock()).toHaveBeenCalledTimes(2)
      } finally {
        vi.useRealTimers()
      }
    })

    it('再試行の待機中に中断すると再送しない', async () => {
      vi.useFakeTimers()
      try {
        fetchMock().mockResolvedValueOnce(new Response('', { status: 503 }))
        const controller = new AbortController()
        const result = expect(apiFetchBlob('/api/export', { signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' })
        await vi.advanceTimersByTimeAsync(1000)
        controller.abort()
        await result
        await vi.advanceTimersByTimeAsync(10_000)
        expect(fetchMock()).toHaveBeenCalledTimes(1)
      } finally {
        vi.useRealTimers()
      }
    })

    it('保存結果が無い 409 のエラーコードと detail を返す', async () => {
      const detail = '結果が保存されていません。'
      fetchMock().mockResolvedValueOnce(Response.json({ detail }, {
        status: 409,
        headers: { 'X-VEA-Error-Code': 'snapshot_result_missing' },
      }))
      await expect(apiFetchBlob('/api/export')).rejects.toMatchObject({
        status: 409, errorCode: 'snapshot_result_missing', message: detail,
      })
    })
  })

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

  it('失敗の状態コードと X-VEA-Error-Code を ApiError で渡す（画面が 409 の理由を見分けるため）', async () => {
    fetchMock().mockResolvedValueOnce(
      new Response('{"detail":"確かめてください"}', {
        status: 409,
        headers: { 'X-VEA-Error-Code': 'directory_verification_required' },
      }),
    )
    const error = await apiPatch('/api/foo', {}).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      message: '確かめてください',
      status: 409,
      errorCode: 'directory_verification_required',
    })

    fetchMock().mockResolvedValueOnce(new Response('{"detail":"x"}', { status: 422 }))
    await expect(apiPost('/api/foo', {})).rejects.toMatchObject({ status: 422, errorCode: null })
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

  it('422 の FastAPI の detail は文字列だけを表示する', async () => {
    fetchMock().mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'パスワードは 12 文字以上にしてください。' }), { status: 422 }),
    )
    await expect(apiPost('/api/foo', {})).rejects.toThrow(/^パスワードは 12 文字以上にしてください。$/)
  })
  it('503 の Retry-After を秒数で保持する（無い・不正なら null）', async () => {
    fetchMock().mockResolvedValueOnce(new Response('busy', { status: 503, headers: { 'Retry-After': '5' } }))
    await expect(apiPost('/api/foo', {})).rejects.toMatchObject({ status: 503, retryAfterSeconds: 5 })
    fetchMock().mockResolvedValueOnce(new Response('busy', { status: 503 }))
    await expect(apiPost('/api/foo', {})).rejects.toMatchObject({ retryAfterSeconds: null })
    fetchMock().mockResolvedValueOnce(
      new Response('busy', { status: 503, headers: { 'Retry-After': 'Wed, 21 Oct 2026 07:28:00 GMT' } }),
    )
    await expect(apiPost('/api/foo', {})).rejects.toMatchObject({ retryAfterSeconds: null })
  })
})
