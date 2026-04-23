/**
 * @vitest-environment happy-dom
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { VCentersPanel } from './VCentersPanel'

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('VCentersPanel protocol selector', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  beforeEach(() => {
    vi.stubGlobal('confirm', vi.fn(() => true))
  })

  it('登録フォームでHTTPを選ぶとPOST payloadにprotocol=httpが含まれる', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(
        jsonResponse({
          id: 'vc-1',
          name: 'lab',
          host: 'vc.example.local',
          protocol: 'http',
          port: 80,
          username: 'admin',
          is_enabled: true,
          created_at: '2026-04-24T00:00:00Z',
        }, 201),
      )
      .mockResolvedValueOnce(jsonResponse([]))
    vi.stubGlobal('fetch', fetchMock)

    render(<VCentersPanel onError={vi.fn()} />)

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/vcenters', expect.any(Object))
    })

    fireEvent.change(screen.getByLabelText('表示名'), { target: { value: 'lab' } })
    fireEvent.change(screen.getByLabelText('ホスト'), { target: { value: 'vc.example.local' } })
    fireEvent.change(screen.getByLabelText('プロトコル'), { target: { value: 'http' } })
    fireEvent.change(screen.getByLabelText('ポート'), { target: { value: '80' } })
    fireEvent.change(screen.getByLabelText('ユーザー'), { target: { value: 'admin' } })
    fireEvent.change(screen.getByLabelText('パスワード'), { target: { value: 'secret' } })

    fireEvent.click(screen.getByRole('button', { name: '追加' }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/vcenters',
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('"protocol":"http"'),
        }),
      )
    })
  })
})
