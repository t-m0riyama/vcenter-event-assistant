import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { TimeZoneProvider } from '../../datetime/TimeZoneProvider'
import { DigestsPanel } from './DigestsPanel'

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderDigests(onError: (e: string | null) => void = vi.fn()) {
  return render(
    <TimeZoneProvider>
      <DigestsPanel onError={onError} />
    </TimeZoneProvider>,
  )
}

describe('DigestsPanel', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('lists digests and shows LLM section and meta when llm_model is set', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.startsWith('/api/digests?')) {
          return Promise.resolve(
            jsonResponse({
              items: [
                {
                  id: 1,
                  period_start: '2026-03-27T00:00:00Z',
                  period_end: '2026-03-28T00:00:00Z',
                  kind: 'daily',
                  body_markdown: '# T\n\n## LLM 要約\n\n- 要点A',
                  status: 'ok',
                  error_message: null,
                  llm_model: 'gpt-4o-mini',
                  created_at: '2026-03-28T01:00:00Z',
                },
              ],
              total: 1,
            }),
          )
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      }),
    )

    renderDigests()

    await waitFor(() => {
      expect(screen.getByRole('navigation', { name: 'ダイジェスト一覧' })).toBeInTheDocument()
    })

    const listNav = screen.getByRole('navigation', { name: 'ダイジェスト一覧' })
    fireEvent.click(within(listNav).getByRole('button', { name: /daily/i }))

    await waitFor(() => {
      expect(screen.getByText(/LLM 要約あり（gpt-4o-mini）/)).toBeInTheDocument()
    })
    expect(screen.getByRole('heading', { level: 2, name: 'LLM 要約' })).toBeInTheDocument()
    expect(screen.getByText('要点A')).toBeInTheDocument()
  })

  it('hides ## LLM 要約 block when llm_model is null', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.startsWith('/api/digests?')) {
          return Promise.resolve(
            jsonResponse({
              items: [
                {
                  id: 2,
                  period_start: '2026-03-27T00:00:00Z',
                  period_end: '2026-03-28T00:00:00Z',
                  kind: 'daily',
                  body_markdown: '# T\n\n## LLM 要約\n\n- 要点A',
                  status: 'ok',
                  error_message: null,
                  llm_model: null,
                  created_at: '2026-03-28T01:00:00Z',
                },
              ],
              total: 1,
            }),
          )
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      }),
    )

    renderDigests()

    await waitFor(() => {
      expect(screen.getByRole('navigation', { name: 'ダイジェスト一覧' })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /daily/i }))

    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1, name: 'T' })).toBeInTheDocument()
    })
    expect(screen.queryByRole('heading', { level: 2, name: 'LLM 要約' })).toBeNull()
    expect(screen.queryByText('要点A')).toBeNull()
    expect(screen.queryByText(/LLM 要約あり/)).toBeNull()
  })

  it('shows error_message when digest has auxiliary error text', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.startsWith('/api/digests?')) {
          return Promise.resolve(
            jsonResponse({
              items: [
                {
                  id: 3,
                  period_start: '2026-03-27T00:00:00Z',
                  period_end: '2026-03-28T00:00:00Z',
                  kind: 'daily',
                  body_markdown: '# X',
                  status: 'ok',
                  error_message: 'LLM 要約は省略（timeout）',
                  llm_model: null,
                  created_at: '2026-03-28T01:00:00Z',
                },
              ],
              total: 1,
            }),
          )
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      }),
    )

    renderDigests()

    await waitFor(() => {
      expect(screen.getByRole('navigation', { name: 'ダイジェスト一覧' })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /daily/i }))

    await waitFor(() => {
      expect(screen.getByText(/LLM 要約は省略/)).toBeInTheDocument()
    })
  })
})
