import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiDelete, apiGet, apiPatch, apiPost } from './api'

const GENERIC = 'リクエストに失敗しました。時間をおいて再度お試しください。'

describe('api', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.stubGlobal('fetch', vi.fn())
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
})
