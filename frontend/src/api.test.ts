import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiDelete, apiGet, apiPatch, apiPost, setToken } from './api'

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

  it('apiGet throws Error with status and body when not ok', async () => {
    fetchMock().mockResolvedValueOnce(new Response('body text', { status: 503 }))
    await expect(apiGet('/api/foo')).rejects.toThrow('503 body text')
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

  it('apiPost throws when not ok', async () => {
    fetchMock().mockResolvedValueOnce(new Response('nope', { status: 400 }))
    await expect(apiPost('/api/foo', {})).rejects.toThrow('400 nope')
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

  it('apiPatch throws when not ok', async () => {
    fetchMock().mockResolvedValueOnce(new Response('bad', { status: 409 }))
    await expect(apiPatch('/api/foo', {})).rejects.toThrow('409 bad')
  })

  it('apiDelete resolves on success', async () => {
    fetchMock().mockResolvedValueOnce(new Response(null, { status: 204 }))
    await expect(apiDelete('/api/foo')).resolves.toBeUndefined()
  })

  it('apiDelete throws when not ok', async () => {
    fetchMock().mockResolvedValueOnce(new Response('gone', { status: 500 }))
    await expect(apiDelete('/api/foo')).rejects.toThrow('500 gone')
  })

  it('sends Authorization when token is set', async () => {
    setToken('secret')
    fetchMock().mockResolvedValueOnce(
      new Response(JSON.stringify({}), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    )
    await apiGet('/api/x')
    expect(fetchMock()).toHaveBeenCalledWith(
      '/api/x',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer secret',
        }),
      }),
    )
  })
})
