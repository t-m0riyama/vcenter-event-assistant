import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { DigestRead } from '../../api/schemas'
import { downloadTextFile } from '../../utils/downloadTextFile'
import { formatIsoDateOnlyInTimeZone, formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { TimeZoneProvider } from '../../datetime/TimeZoneProvider'
import { DISPLAY_TIME_ZONE_STORAGE_KEY } from '../../datetime/timeZoneStorage'
import { buildDigestDownloadFilename } from './buildDigestDownloadFilename'
import { getDigestBodyMarkdownForDisplay } from './getDigestBodyMarkdownForDisplay'
import { DIGEST_LIST_PAGE_SIZE, DigestsPanel } from './DigestsPanel'

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

function createDeferredResponse() {
  let resolve: ((value: Response) => void) | null = null
  const promise = new Promise<Response>((r) => {
    resolve = r
  })
  return {
    promise,
    resolve: (response: Response) => {
      if (resolve == null) throw new Error('deferred resolver is not ready')
      resolve(response)
    },
  }
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

    fireEvent.click(within(screen.getByRole('navigation', { name: 'ダイジェスト一覧' })).getByRole('button', { name: /daily/i }))

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

  it('一覧ナビに開始日付のみ表示し、レンジや時刻付き開始ラベルは出さない', async () => {
    const prevTz = localStorage.getItem(DISPLAY_TIME_ZONE_STORAGE_KEY)
    localStorage.setItem(DISPLAY_TIME_ZONE_STORAGE_KEY, 'Asia/Tokyo')
    const periodStart = '2026-03-27T00:00:00Z'
    const periodEnd = '2026-03-28T00:00:00Z'
    const expectedStartDateLabel = formatIsoDateOnlyInTimeZone(periodStart, 'Asia/Tokyo')
    const rangeLabel = `${formatIsoInTimeZone(periodStart, 'Asia/Tokyo', { omitSeconds: true })} 〜 ${formatIsoInTimeZone(periodEnd, 'Asia/Tokyo', { omitSeconds: true })}`
    const startWithTimeLabel = formatIsoInTimeZone(periodStart, 'Asia/Tokyo', { omitSeconds: true })

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
      expect(within(listNav).getByText(expectedStartDateLabel)).toBeInTheDocument()
      expect(within(listNav).queryByText('〜')).toBeNull()
      expect(within(listNav).queryByText(rangeLabel)).toBeNull()
      expect(within(listNav).queryByText(startWithTimeLabel)).toBeNull()
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

  it('shows LLM failure badge for legacy ok + error_message rows', async () => {
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

    const listNav = screen.getByRole('navigation', { name: 'ダイジェスト一覧' })
    expect(within(listNav).getByText('LLM 失敗')).toBeInTheDocument()

    fireEvent.click(within(listNav).getByRole('button', { name: /daily/i }))

    await waitFor(() => {
      expect(screen.getByText(/LLM 要約は省略/)).toBeInTheDocument()
    })
    expect(screen.getByText(/テンプレート本文は保存済みですが/)).toBeInTheDocument()
  })

  it('shows ok_llm_failed status badge in list', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.startsWith('/api/digests?')) {
          return Promise.resolve(
            jsonResponse({
              items: [
                {
                  id: 4,
                  period_start: '2026-03-27T00:00:00Z',
                  period_end: '2026-03-28T00:00:00Z',
                  kind: 'daily',
                  body_markdown: '# X',
                  status: 'ok_llm_failed',
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
      expect(within(screen.getByRole('navigation', { name: 'ダイジェスト一覧' })).getByText('LLM 失敗')).toBeInTheDocument()
    })
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

    fireEvent.click(within(screen.getByRole('navigation', { name: 'ダイジェスト一覧' })).getByRole('button', { name: /daily/i }))

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

    fireEvent.click(within(screen.getByRole('navigation', { name: 'ダイジェスト一覧' })).getByRole('button', { name: /daily/i }))

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

  it('kind切替で kind クエリ連動・offset初期化・選択解除して再取得する', async () => {
    const fetchCalls: string[] = []
    const page2Digest: DigestRead = {
      id: 201,
      period_start: '2026-03-27T00:00:00Z',
      period_end: '2026-03-28T00:00:00Z',
      kind: 'daily',
      body_markdown: '# Page2',
      status: 'ok',
      error_message: null,
      llm_model: null,
      created_at: '2026-03-28T01:00:00Z',
    }
    const weeklyDigest: DigestRead = {
      id: 301,
      period_start: '2026-03-20T00:00:00Z',
      period_end: '2026-03-27T00:00:00Z',
      kind: 'weekly',
      body_markdown: '# Weekly',
      status: 'ok',
      error_message: null,
      llm_model: null,
      created_at: '2026-03-28T01:00:00Z',
    }

    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = input instanceof Request ? input.url : String(input)
        fetchCalls.push(url)
        if (!url.includes('/api/digests?')) return Promise.reject(new Error(`unexpected fetch: ${url}`))
        const search = new URL(url, 'http://localhost').searchParams
        const kind = search.get('kind')
        const offset = search.get('offset')

        if (kind === 'weekly' && offset === '0') {
          return Promise.resolve(jsonResponse({ items: [weeklyDigest], total: 1 }))
        }
        if (kind === null && offset === String(DIGEST_LIST_PAGE_SIZE)) {
          return Promise.resolve(jsonResponse({ items: [page2Digest], total: DIGEST_LIST_PAGE_SIZE + 1 }))
        }
        if (kind === null && offset === '0') {
          return Promise.resolve(
            jsonResponse({
              items: [
                {
                  ...page2Digest,
                  id: 101,
                  body_markdown: '# Page1',
                },
              ],
              total: DIGEST_LIST_PAGE_SIZE + 1,
            }),
          )
        }
        if (kind === null) {
          return Promise.resolve(jsonResponse({ items: [page2Digest], total: DIGEST_LIST_PAGE_SIZE + 1 }))
        }
        return Promise.reject(new Error(`unexpected query: ${url}`))
      }),
    )

    renderDigests()

    await waitFor(() => {
      expect(screen.getByRole('navigation', { name: 'ダイジェスト一覧' })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: '次へ' }))
    const listNav = await screen.findByRole('navigation', { name: 'ダイジェスト一覧' })
    await waitFor(() => {
      expect(within(listNav).getByText('daily')).toBeInTheDocument()
    })
    fireEvent.click(within(listNav).getAllByRole('button')[0])
    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1, name: 'Page2' })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'weekly' }))
    await waitFor(() => {
      expect(within(screen.getByRole('navigation', { name: 'ダイジェスト一覧' })).getByText('weekly')).toBeInTheDocument()
    })
    expect(screen.getByText('左の一覧からダイジェストを選んでください。')).toBeInTheDocument()
    expect(fetchCalls.some((u) => u.includes('kind=weekly') && u.includes('offset=0'))).toBe(true)
  })

  it('0件表示は選択中kindに応じた文言を出す', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (!url.startsWith('/api/digests?')) return Promise.reject(new Error(`unexpected fetch: ${url}`))
        return Promise.resolve(jsonResponse({ items: [], total: 0 }))
      }),
    )

    renderDigests()

    await waitFor(() => {
      expect(screen.getByText('保存済みのダイジェストはありません。')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'monthly' }))
    await waitFor(() => {
      expect(screen.getByText('monthly の保存済みダイジェストはありません。')).toBeInTheDocument()
    })
  })

  it('競合した古いレスポンスは最新状態を上書きしない', async () => {
    const firstRequest = createDeferredResponse()
    const secondRequest = createDeferredResponse()
    let callCount = 0

    vi.stubGlobal(
      'fetch',
      vi.fn(() => {
        callCount += 1
        if (callCount === 1) return firstRequest.promise
        if (callCount === 2) return secondRequest.promise
        return Promise.reject(new Error(`unexpected fetch call: ${callCount}`))
      }),
    )

    const onError1 = vi.fn()
    const onError2 = vi.fn()
    const { rerender } = render(
      <TimeZoneProvider>
        <DigestsPanel onError={onError1} />
      </TimeZoneProvider>,
    )
    rerender(
      <TimeZoneProvider>
        <DigestsPanel onError={onError2} />
      </TimeZoneProvider>,
    )

    secondRequest.resolve(
      jsonResponse({
        items: [
          {
            id: 2,
            period_start: '2026-03-27T00:00:00Z',
            period_end: '2026-03-28T00:00:00Z',
            kind: 'weekly',
            body_markdown: '# Newest',
            status: 'ok',
            error_message: null,
            llm_model: null,
            created_at: '2026-03-28T02:00:00Z',
          },
        ],
        total: 1,
      }),
    )

    await waitFor(() => {
      expect(within(screen.getByRole('navigation', { name: 'ダイジェスト一覧' })).getByText('weekly')).toBeInTheDocument()
    })

    firstRequest.resolve(
      jsonResponse({
        items: [
          {
            id: 3,
            period_start: '2026-03-20T00:00:00Z',
            period_end: '2026-03-27T00:00:00Z',
            kind: 'daily',
            body_markdown: '# Stale',
            status: 'ok',
            error_message: null,
            llm_model: null,
            created_at: '2026-03-28T03:00:00Z',
          },
        ],
        total: 1,
      }),
    )

    await waitFor(() => {
      const listNav = screen.getByRole('navigation', { name: 'ダイジェスト一覧' })
      expect(within(listNav).getByText('weekly')).toBeInTheDocument()
      expect(within(listNav).queryByText('daily')).toBeNull()
    })
  })
})
