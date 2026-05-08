import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { TimeZoneProvider } from '../../datetime/TimeZoneProvider'
import { TimelinePanel } from './TimelinePanel'

const TIMELINE_PANEL_TEST_TIMEOUT_MS = 15_000

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderTimeline(onError: (e: string | null) => void = vi.fn()) {
  return render(
    <TimeZoneProvider>
      <TimelinePanel onError={onError} />
    </TimeZoneProvider>,
  )
}

describe(
  'TimelinePanel',
  { timeout: TIMELINE_PANEL_TEST_TIMEOUT_MS },
  () => {
    afterEach(() => {
      localStorage.clear()
      vi.unstubAllGlobals()
    })

    it('生成前は空状態のヒントを表示し、タイムラインは描画しない', async () => {
      const fetchMock = vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.endsWith('/api/vcenters')) {
          return Promise.resolve(jsonResponse([]))
        }
        if (url.includes('/api/incident-timeline/snapshots/manual?')) {
          return Promise.resolve(jsonResponse({ items: [], total: 0, limit: 20, offset: 0 }))
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      })
      vi.stubGlobal('fetch', fetchMock)

      renderTimeline()
      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalled()
      })

      expect(
        screen.getByText('「タイムラインを生成」を押すと、指定期間のインシデント統合タイムラインを表示します。'),
      ).toBeInTheDocument()
      expect(screen.queryByText('インシデント統合タイムライン')).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'タイムラインを生成' })).toBeEnabled()
    })

    it('生成前でも監査ビューから保存済みスナップショットを選択してタイムラインへ切り替えできる', async () => {
      const timelinePayloads: Record<string, unknown>[] = []
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.endsWith('/api/vcenters')) {
          return Promise.resolve(jsonResponse([]))
        }
        if (url.includes('/api/incident-timeline/snapshots/manual?')) {
          return Promise.resolve(
            jsonResponse({
              items: [
                {
                  snapshot_id: '00000000-0000-0000-0000-000000000001',
                  from: '2026-03-20T00:00:00Z',
                  to: '2026-03-21T00:00:00Z',
                  operator_note: '保存済みA',
                  timestamp_utc: '2026-03-21T01:00:00Z',
                  build_request_payload: {
                    from: '2026-03-20T00:00:00Z',
                    to: '2026-03-21T00:00:00Z',
                    alert_top_n: 9,
                  },
                },
              ],
              total: 1,
              limit: 20,
              offset: 0,
            }),
          )
        }
        if (url.endsWith('/api/incident-timeline') && init?.method === 'POST') {
          timelinePayloads.push(JSON.parse(String(init.body)) as Record<string, unknown>)
          return Promise.resolve(
            jsonResponse({
              columns: [
                {
                  timestamp_utc: '2026-03-20T00:00:00Z',
                  items: [
                    {
                      timestamp_utc: '2026-03-20T00:00:00Z',
                      kind: 'alert',
                      title: '保存済みAのタイムライン',
                    },
                  ],
                  visible_items: [
                    {
                      timestamp_utc: '2026-03-20T00:00:00Z',
                      kind: 'alert',
                      title: '保存済みAのタイムライン',
                    },
                  ],
                  hidden_count: 0,
                },
              ],
            }),
          )
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      })
      vi.stubGlobal('fetch', fetchMock)

      renderTimeline()
      await waitFor(() => {
        expect(screen.getByRole('button', { name: '保存済みA' })).toBeInTheDocument()
      })

      fireEvent.click(screen.getByRole('button', { name: '保存済みA' }))
      await waitFor(() => {
        expect(timelinePayloads.length).toBe(1)
      })
      expect(timelinePayloads[0]?.from).toBe('2026-03-20T00:00:00Z')
      expect(timelinePayloads[0]?.to).toBe('2026-03-21T00:00:00Z')
      expect(timelinePayloads[0]?.alert_top_n).toBe(9)
      expect(screen.getByText('インシデント統合タイムライン')).toBeInTheDocument()
      expect(screen.getByText('保存済みAのタイムライン')).toBeInTheDocument()
    })

    it('生成ボタンで POST /api/incident-timeline が期待した本文で呼ばれる', async () => {
      const timelinePayloadRef: { current: Record<string, unknown> | null } = { current: null }
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.endsWith('/api/vcenters')) {
          return Promise.resolve(
            jsonResponse([{ id: '550e8400-e29b-41d4-a716-446655440000', name: 'vc1' }]),
          )
        }
        if (url.endsWith('/api/incident-timeline') && init?.method === 'POST') {
          timelinePayloadRef.current = JSON.parse(String(init.body)) as Record<string, unknown>
          return Promise.resolve(jsonResponse({ columns: [] }))
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      })
      vi.stubGlobal('fetch', fetchMock)

      renderTimeline()
      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalled()
      })

      fireEvent.click(screen.getByRole('checkbox', { name: /^CPU 使用率$/ }))
      fireEvent.click(screen.getByRole('checkbox', { name: /^メモリ使用率$/ }))
      fireEvent.change(screen.getByRole('spinbutton', { name: 'CPU 閾値（%）' }), {
        target: { value: '90' },
      })
      fireEvent.click(screen.getByRole('button', { name: 'タイムラインを生成' }))

      await waitFor(() => {
        expect(timelinePayloadRef.current).not.toBeNull()
      })
      if (!timelinePayloadRef.current) {
        throw new Error('タイムライン本文が取得できませんでした')
      }
      const body = timelinePayloadRef.current
      expect(typeof body.from).toBe('string')
      expect(typeof body.to).toBe('string')
      expect(body.include_period_metrics_cpu).toBe(true)
      expect(body.include_period_metrics_memory).toBe(true)
      expect(body.include_period_metrics_disk_io).toBe(false)
      expect(body.include_period_metrics_network_io).toBe(false)
      expect(body.metric_threshold_cpu_pct).toBe(90)
      expect(body.metric_threshold_memory_pct).toBe(85)
      expect(body.metric_threshold_disk_pct).toBe(75)
      expect(body.metric_threshold_network_pct).toBe(75)
      expect(body.alert_top_n).toBe(7)
      expect(body).not.toHaveProperty('sort_order')
      expect(body).not.toHaveProperty('messages')
    })

    it('alert_top_n を指定して生成すると本文に含める', async () => {
      const timelinePayloadRef: { current: Record<string, unknown> | null } = { current: null }
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.endsWith('/api/vcenters')) {
          return Promise.resolve(jsonResponse([]))
        }
        if (url.endsWith('/api/incident-timeline') && init?.method === 'POST') {
          timelinePayloadRef.current = JSON.parse(String(init.body)) as Record<string, unknown>
          return Promise.resolve(jsonResponse({ columns: [] }))
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      })
      vi.stubGlobal('fetch', fetchMock)

      renderTimeline()
      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalled()
      })

      fireEvent.change(screen.getByRole('spinbutton', { name: 'アラート上位件数' }), {
        target: { value: '12' },
      })
      fireEvent.click(screen.getByRole('button', { name: 'タイムラインを生成' }))

      await waitFor(() => {
        expect(timelinePayloadRef.current).not.toBeNull()
      })
      if (!timelinePayloadRef.current) {
        throw new Error('タイムライン本文が取得できませんでした')
      }
      expect(timelinePayloadRef.current.alert_top_n).toBe(12)
      expect(timelinePayloadRef.current).not.toHaveProperty('sort_order')
    })

    it('ソート順トグルを localStorage に保存し再表示時に復元する', async () => {
      localStorage.setItem('vea.timeline.sort_order', 'asc')

      const fetchMock = vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.endsWith('/api/vcenters')) {
          return Promise.resolve(jsonResponse([]))
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      })
      vi.stubGlobal('fetch', fetchMock)

      const { unmount } = renderTimeline()
      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalled()
      })
      expect(screen.getByRole('button', { name: '表示順: 昇順' })).toBeInTheDocument()

      fireEvent.click(screen.getByRole('button', { name: '表示順: 昇順' }))
      expect(localStorage.getItem('vea.timeline.sort_order')).toBe('desc')
      expect(screen.getByRole('button', { name: '表示順: 降順' })).toBeInTheDocument()

      unmount()
      renderTimeline()
      expect(screen.getByRole('button', { name: '表示順: 降順' })).toBeInTheDocument()
    })

    it('alert_top_n を localStorage から復元して送信本文に反映する', async () => {
      localStorage.setItem('vea.timeline.alert_top_n', '12')
      const timelinePayloadRef: { current: Record<string, unknown> | null } = { current: null }
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.endsWith('/api/vcenters')) {
          return Promise.resolve(jsonResponse([]))
        }
        if (url.endsWith('/api/incident-timeline') && init?.method === 'POST') {
          timelinePayloadRef.current = JSON.parse(String(init.body)) as Record<string, unknown>
          return Promise.resolve(jsonResponse({ columns: [] }))
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      })
      vi.stubGlobal('fetch', fetchMock)

      renderTimeline()
      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalled()
      })
      expect(screen.getByRole('spinbutton', { name: 'アラート上位件数' })).toHaveValue(12)

      fireEvent.click(screen.getByRole('button', { name: 'タイムラインを生成' }))
      await waitFor(() => {
        expect(timelinePayloadRef.current).not.toBeNull()
      })
      expect(timelinePayloadRef.current?.alert_top_n).toBe(12)
    })

    it('成功時にインシデント統合タイムラインを描画する', async () => {
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.endsWith('/api/vcenters')) {
          return Promise.resolve(jsonResponse([]))
        }
        if (url.endsWith('/api/incident-timeline') && init?.method === 'POST') {
          return Promise.resolve(
            jsonResponse({
              columns: [
                {
                  timestamp_utc: '2026-05-07T00:00:00Z',
                  items: [
                    { timestamp_utc: '2026-05-07T00:00:00Z', kind: 'alert', title: '重大アラート' },
                  ],
                  visible_items: [
                    { timestamp_utc: '2026-05-07T00:00:00Z', kind: 'alert', title: '重大アラート' },
                  ],
                  hidden_count: 0,
                },
              ],
            }),
          )
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      })
      vi.stubGlobal('fetch', fetchMock)

      renderTimeline()
      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalled()
      })

      fireEvent.click(screen.getByRole('button', { name: 'タイムラインを生成' }))

      await waitFor(() => {
        expect(screen.getByText('インシデント統合タイムライン')).toBeInTheDocument()
      })
      expect(screen.getByText('重大アラート')).toHaveClass('incident-timeline__item--alert')
    })

    it('自動トリガー項目の timestamp_utc が +00:00 形式でも描画できる', async () => {
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.endsWith('/api/vcenters')) {
          return Promise.resolve(jsonResponse([]))
        }
        if (url.endsWith('/api/incident-timeline') && init?.method === 'POST') {
          return Promise.resolve(
            jsonResponse({
              columns: [
                {
                  timestamp_utc: '2026-05-07T00:00:00+00:00',
                  items: [
                    {
                      timestamp_utc: '2026-05-07T00:00:00+00:00',
                      kind: 'alert',
                      title: '自動スナップショット候補: critical_burst',
                      trigger_id: 'critical_burst',
                    },
                  ],
                  visible_items: [
                    {
                      timestamp_utc: '2026-05-07T00:00:00+00:00',
                      kind: 'alert',
                      title: '自動スナップショット候補: critical_burst',
                      trigger_id: 'critical_burst',
                    },
                  ],
                  hidden_count: 0,
                },
              ],
            }),
          )
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      })
      vi.stubGlobal('fetch', fetchMock)

      renderTimeline()
      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalled()
      })

      fireEvent.click(screen.getByRole('button', { name: 'タイムラインを生成' }))
      await waitFor(() => {
        expect(screen.getByText('インシデント統合タイムライン')).toBeInTheDocument()
      })
      expect(screen.getByText('自動スナップショット候補: critical_burst')).toBeInTheDocument()
    })

    it('生成中はボタンが無効になり aria-busy が true になる', async () => {
      let releasePost: (() => void) | undefined
      const postPromise = new Promise<Response>((resolve) => {
        releasePost = () => {
          resolve(jsonResponse({ columns: [] }))
        }
      })

      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.endsWith('/api/vcenters')) {
          return Promise.resolve(jsonResponse([]))
        }
        if (url.endsWith('/api/incident-timeline') && init?.method === 'POST') {
          return postPromise
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      })
      vi.stubGlobal('fetch', fetchMock)

      renderTimeline()
      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalled()
      })

      fireEvent.click(screen.getByRole('button', { name: 'タイムラインを生成' }))

      const loadingBtn = await screen.findByRole('button', { name: 'タイムライン生成中' })
      expect(loadingBtn).toBeDisabled()
      expect(loadingBtn).toHaveAttribute('aria-busy', 'true')

      releasePost?.()

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'タイムラインを生成' })).toBeInTheDocument()
      })
    })

    it('API エラー時は onError コールバックを呼びタイムラインは描画しない', async () => {
      const onError = vi.fn()
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.endsWith('/api/vcenters')) {
          return Promise.resolve(jsonResponse([]))
        }
        if (url.endsWith('/api/incident-timeline') && init?.method === 'POST') {
          return Promise.resolve(new Response('boom', { status: 500 }))
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      })
      vi.stubGlobal('fetch', fetchMock)

      renderTimeline(onError)
      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalled()
      })

      fireEvent.click(screen.getByRole('button', { name: 'タイムラインを生成' }))

      await waitFor(() => {
        expect(onError).toHaveBeenCalled()
      })
      expect(onError.mock.calls.at(-1)?.[0]).toEqual(expect.stringContaining('500'))
      expect(screen.queryByText('インシデント統合タイムライン')).not.toBeInTheDocument()
      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'タイムラインを生成' })).toBeEnabled()
      })
      expect(screen.queryByRole('button', { name: 'タイムライン生成中' })).not.toBeInTheDocument()
    })

    it('手動スナップショット保存は operator_note 必須で、入力後に保存 API を呼ぶ', async () => {
      const snapshotPayloadRef: { current: Record<string, unknown> | null } = { current: null }
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.endsWith('/api/vcenters')) {
          return Promise.resolve(jsonResponse([]))
        }
        if (url.endsWith('/api/incident-timeline') && init?.method === 'POST') {
          return Promise.resolve(jsonResponse({ columns: [] }))
        }
        if (url.endsWith('/api/incident-timeline/snapshots/manual') && init?.method === 'POST') {
          snapshotPayloadRef.current = JSON.parse(String(init.body)) as Record<string, unknown>
          return Promise.resolve(
            jsonResponse(
              {
                snapshot_id: '00000000-0000-0000-0000-000000000001',
                operator_note: String(snapshotPayloadRef.current.operator_note ?? ''),
                timestamp_utc: '2026-03-22T01:23:45Z',
                build_request_payload: {
                  from: '2026-03-22T00:00:00Z',
                  to: '2026-03-23T00:00:00Z',
                },
              },
              201,
            ),
          )
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      })
      vi.stubGlobal('fetch', fetchMock)

      renderTimeline()
      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalled()
      })

      fireEvent.click(screen.getByRole('button', { name: 'タイムラインを生成' }))
      await waitFor(() => {
        expect(screen.getByText('インシデント統合タイムライン')).toBeInTheDocument()
      })

      const saveButton = screen.getByRole('button', { name: 'スナップショットを保存' })
      const noteInput = screen.getByLabelText('運用メモ（必須）')
      expect(saveButton).toBeDisabled()

      fireEvent.change(noteInput, { target: { value: 'エスカレーション前の手動保存' } })
      expect(saveButton).toBeEnabled()

      fireEvent.click(saveButton)
      await waitFor(() => {
        expect(snapshotPayloadRef.current).not.toBeNull()
      })
      expect(snapshotPayloadRef.current?.operator_note).toBe('エスカレーション前の手動保存')
    })

    it('手動保存後に監査ビューを表示し、一覧 API の結果を描画する', async () => {
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.endsWith('/api/vcenters')) {
          return Promise.resolve(jsonResponse([]))
        }
        if (url.endsWith('/api/incident-timeline') && init?.method === 'POST') {
          return Promise.resolve(jsonResponse({ columns: [] }))
        }
        if (url.endsWith('/api/incident-timeline/snapshots/manual') && init?.method === 'POST') {
          return Promise.resolve(
            jsonResponse(
              {
                snapshot_id: '00000000-0000-0000-0000-000000000123',
                operator_note: '監査表示テスト',
                timestamp_utc: '2026-03-22T01:23:45Z',
                build_request_payload: {
                  from: '2026-03-22T00:00:00Z',
                  to: '2026-03-23T00:00:00Z',
                },
              },
              201,
            ),
          )
        }
        if (
          url.includes('/api/incident-timeline/snapshots/manual?') &&
          init?.method !== 'POST'
        ) {
          return Promise.resolve(
            jsonResponse({
              items: [
                {
                  snapshot_id: '00000000-0000-0000-0000-000000000123',
                  from: '2026-03-22T00:00:00Z',
                  to: '2026-03-23T00:00:00Z',
                  operator_note: '監査表示テスト',
                  timestamp_utc: '2026-03-22T01:23:45Z',
                  build_request_payload: {
                    from: '2026-03-22T00:00:00Z',
                    to: '2026-03-23T00:00:00Z',
                  },
                },
              ],
              total: 1,
              limit: 20,
              offset: 0,
            }),
          )
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      })
      vi.stubGlobal('fetch', fetchMock)

      renderTimeline()
      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalled()
      })

      fireEvent.click(screen.getByRole('button', { name: 'タイムラインを生成' }))
      await waitFor(() => {
        expect(screen.getByText('インシデント統合タイムライン')).toBeInTheDocument()
      })

      fireEvent.change(screen.getByLabelText('運用メモ（必須）'), {
        target: { value: '監査表示テスト' },
      })
      fireEvent.click(screen.getByRole('button', { name: 'スナップショットを保存' }))

      await waitFor(() => {
        expect(
          fetchMock.mock.calls.some(([input]) =>
            String(input).includes('/api/incident-timeline/snapshots/manual?'),
          ),
        ).toBe(true)
      })
      expect(screen.getByText('手動スナップショット監査ビュー')).toBeInTheDocument()
      const selectedSection = screen.getByLabelText('選択中スナップショット')
      expect(within(selectedSection).getByText('監査表示テスト')).toBeInTheDocument()
    })

    it('監査ビューで複数スナップショットを切り替えて表示できる', async () => {
      const timelinePayloads: Record<string, unknown>[] = []
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.endsWith('/api/vcenters')) {
          return Promise.resolve(jsonResponse([]))
        }
        if (url.endsWith('/api/incident-timeline') && init?.method === 'POST') {
          timelinePayloads.push(JSON.parse(String(init.body)) as Record<string, unknown>)
          return Promise.resolve(jsonResponse({ columns: [] }))
        }
        if (
          url.includes('/api/incident-timeline/snapshots/manual?') &&
          init?.method !== 'POST'
        ) {
          return Promise.resolve(
            jsonResponse({
              items: [
                {
                  snapshot_id: '00000000-0000-0000-0000-000000000001',
                  from: '2026-03-20T00:00:00Z',
                  to: '2026-03-21T00:00:00Z',
                  operator_note: '一次調査メモ',
                  timestamp_utc: '2026-03-22T01:23:45Z',
                  build_request_payload: {
                    from: '2026-03-20T00:00:00Z',
                    to: '2026-03-21T00:00:00Z',
                  },
                },
                {
                  snapshot_id: '00000000-0000-0000-0000-000000000002',
                  from: '2026-03-22T00:00:00Z',
                  to: '2026-03-23T00:00:00Z',
                  operator_note: '二次調査メモ',
                  timestamp_utc: '2026-03-22T01:33:45Z',
                  build_request_payload: {
                    from: '2026-03-22T00:00:00Z',
                    to: '2026-03-23T00:00:00Z',
                    include_period_metrics_cpu: true,
                  },
                },
              ],
              total: 2,
              limit: 20,
              offset: 0,
            }),
          )
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      })
      vi.stubGlobal('fetch', fetchMock)

      renderTimeline()
      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalled()
      })

      fireEvent.click(screen.getByRole('button', { name: 'タイムラインを生成' }))
      await waitFor(() => {
        expect(screen.getByText('手動スナップショット監査ビュー')).toBeInTheDocument()
      })

      expect(screen.getByText('選択中スナップショット')).toBeInTheDocument()
      const selectedSection = screen.getByLabelText('選択中スナップショット')
      expect(within(selectedSection).getByText('一次調査メモ')).toBeInTheDocument()

      fireEvent.click(screen.getByRole('button', { name: '二次調査メモ' }))
      expect(within(selectedSection).getByText('二次調査メモ')).toBeInTheDocument()
      expect(selectedSection).toHaveTextContent('2026-03-22T01:33:45Z')
      await waitFor(() => {
        expect(timelinePayloads.length).toBeGreaterThan(1)
      })
      const lastPayload = timelinePayloads.at(-1)
      expect(lastPayload?.from).toBe('2026-03-22T00:00:00Z')
      expect(lastPayload?.to).toBe('2026-03-23T00:00:00Z')
      expect(lastPayload?.include_period_metrics_cpu).toBe(true)
    })

    it('スナップショット選択時に bucket_start_utc/bucket_end_utc が null でもタイムラインを表示できる', async () => {
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.endsWith('/api/vcenters')) {
          return Promise.resolve(jsonResponse([]))
        }
        if (
          url.includes('/api/incident-timeline/snapshots/manual?') &&
          init?.method !== 'POST'
        ) {
          return Promise.resolve(
            jsonResponse({
              items: [
                {
                  snapshot_id: '00000000-0000-0000-0000-0000000000aa',
                  from: '2026-03-24T00:00:00Z',
                  to: '2026-03-25T00:00:00Z',
                  operator_note: 'null bucket テスト',
                  timestamp_utc: '2026-03-25T01:00:00Z',
                  build_request_payload: {
                    from: '2026-03-24T00:00:00Z',
                    to: '2026-03-25T00:00:00Z',
                  },
                },
              ],
              total: 1,
              limit: 20,
              offset: 0,
            }),
          )
        }
        if (url.endsWith('/api/incident-timeline') && init?.method === 'POST') {
          return Promise.resolve(
            jsonResponse({
              columns: [
                {
                  timestamp_utc: '2026-03-24T00:00:00Z',
                  bucket_start_utc: null,
                  bucket_end_utc: null,
                  items: [
                    {
                      timestamp_utc: '2026-03-24T00:00:00Z',
                      kind: 'event',
                      title: 'null bucket でも表示',
                    },
                  ],
                  visible_items: [
                    {
                      timestamp_utc: '2026-03-24T00:00:00Z',
                      kind: 'event',
                      title: 'null bucket でも表示',
                    },
                  ],
                  hidden_count: 0,
                },
              ],
            }),
          )
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      })
      vi.stubGlobal('fetch', fetchMock)

      renderTimeline()
      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'null bucket テスト' })).toBeInTheDocument()
      })

      fireEvent.click(screen.getByRole('button', { name: 'null bucket テスト' }))
      await waitFor(() => {
        expect(screen.getByText('インシデント統合タイムライン')).toBeInTheDocument()
      })
      expect(screen.getByText('null bucket でも表示')).toBeInTheDocument()
    })
  },
)
