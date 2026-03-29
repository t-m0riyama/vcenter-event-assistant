import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { DigestRead } from '../../api/schemas'
import { downloadTextFile } from '../../utils/downloadTextFile'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { TimeZoneProvider } from '../../datetime/TimeZoneProvider'
import { DISPLAY_TIME_ZONE_STORAGE_KEY } from '../../datetime/timeZoneStorage'
import { buildDigestDownloadFilename } from './buildDigestDownloadFilename'
import { getDigestBodyMarkdownForDisplay } from './getDigestBodyMarkdownForDisplay'
import { DigestsPanel } from './DigestsPanel'

vi.mock('../../utils/downloadTextFile', () => ({
  downloadTextFile: vi.fn(),
}))

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

  it('一覧ナビの各行に「作成」と秒なしの created_at を表示する', async () => {
    const prevTz = localStorage.getItem(DISPLAY_TIME_ZONE_STORAGE_KEY)
    localStorage.setItem(DISPLAY_TIME_ZONE_STORAGE_KEY, 'Asia/Tokyo')
    const createdAt = '2026-03-28T01:00:00Z'
    const expectedCreatedLine = `作成 ${formatIsoInTimeZone(createdAt, 'Asia/Tokyo', { omitSeconds: true })}`

    try {
      vi.stubGlobal(
        'fetch',
        vi.fn((input: RequestInfo | URL) => {
          const url = String(input)
          if (url.startsWith('/api/digests?')) {
            return Promise.resolve(
              jsonResponse({
                items: [
                  {
                    id: 10,
                    period_start: '2026-03-27T00:00:00Z',
                    period_end: '2026-03-28T00:00:00Z',
                    kind: 'daily',
                    body_markdown: '# T',
                    status: 'ok',
                    error_message: null,
                    llm_model: null,
                    created_at: createdAt,
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
      expect(within(listNav).getByText(expectedCreatedLine)).toBeInTheDocument()
    } finally {
      if (prevTz === null) {
        localStorage.removeItem(DISPLAY_TIME_ZONE_STORAGE_KEY)
      } else {
        localStorage.setItem(DISPLAY_TIME_ZONE_STORAGE_KEY, prevTz)
      }
    }
  })

  it('一覧ナビに集計期間（開始・終了）は表示しない', async () => {
    const prevTz = localStorage.getItem(DISPLAY_TIME_ZONE_STORAGE_KEY)
    localStorage.setItem(DISPLAY_TIME_ZONE_STORAGE_KEY, 'Asia/Tokyo')
    const periodStart = '2026-03-27T00:00:00Z'
    const periodEnd = '2026-03-28T00:00:00Z'
    const rangeLabel = `${formatIsoInTimeZone(periodStart, 'Asia/Tokyo', { omitSeconds: true })} 〜 ${formatIsoInTimeZone(periodEnd, 'Asia/Tokyo', { omitSeconds: true })}`
    const startOnlyLabel = formatIsoInTimeZone(periodStart, 'Asia/Tokyo', { omitSeconds: true })

    try {
      vi.stubGlobal(
        'fetch',
        vi.fn((input: RequestInfo | URL) => {
          const url = String(input)
          if (url.startsWith('/api/digests?')) {
            return Promise.resolve(
              jsonResponse({
                items: [
                  {
                    id: 11,
                    period_start: periodStart,
                    period_end: periodEnd,
                    kind: 'daily',
                    body_markdown: '# T',
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

      const listNav = screen.getByRole('navigation', { name: 'ダイジェスト一覧' })
      expect(within(listNav).getByText('daily')).toBeInTheDocument()
      expect(within(listNav).queryByText(rangeLabel)).toBeNull()
      expect(within(listNav).queryByText(startOnlyLabel)).toBeNull()
    } finally {
      if (prevTz === null) {
        localStorage.removeItem(DISPLAY_TIME_ZONE_STORAGE_KEY)
      } else {
        localStorage.setItem(DISPLAY_TIME_ZONE_STORAGE_KEY, prevTz)
      }
    }
  })

  it('一覧はスクロール領域にラップされ、詳細パネルに sticky 用クラスが付く', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.startsWith('/api/digests?')) {
          return Promise.resolve(
            jsonResponse({
              items: [
                {
                  id: 99,
                  period_start: '2026-03-27T00:00:00Z',
                  period_end: '2026-03-28T00:00:00Z',
                  kind: 'daily',
                  body_markdown: '# T',
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

    const { container } = renderDigests()

    await waitFor(() => {
      expect(screen.getByRole('navigation', { name: 'ダイジェスト一覧' })).toBeInTheDocument()
    })

    expect(screen.getByTestId('digests-list-scroll-region')).toBeInTheDocument()
    expect(container.querySelector('.digests-detail.digests-detail--sticky')).not.toBeNull()
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

  it('Markdown をダウンロードで downloadTextFile にファイル名と表示用本文を渡す', async () => {
    vi.mocked(downloadTextFile).mockClear()

    const digestRow: DigestRead = {
      id: 7,
      period_start: '2026-03-27T00:00:00Z',
      period_end: '2026-03-28T00:00:00Z',
      kind: 'daily',
      body_markdown: '# T\n\n## LLM 要約\n\n- x',
      status: 'ok',
      error_message: null,
      llm_model: null,
      created_at: '2026-03-28T01:00:00Z',
    }

    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.startsWith('/api/digests?')) {
          return Promise.resolve(
            jsonResponse({
              items: [digestRow],
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

    fireEvent.click(screen.getByRole('button', { name: /Markdown をダウンロード/i }))

    expect(downloadTextFile).toHaveBeenCalledTimes(1)
    expect(downloadTextFile).toHaveBeenCalledWith(
      buildDigestDownloadFilename(digestRow),
      getDigestBodyMarkdownForDisplay(digestRow),
    )
  })
})
