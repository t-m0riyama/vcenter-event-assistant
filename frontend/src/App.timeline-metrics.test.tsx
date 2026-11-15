/**
 * @vitest-environment happy-dom
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// グラフのタブへ渡された条件をそのまま表示するスタブ
vi.mock('./panels/metrics/MetricsPanel', () => ({
  MetricsPanel: ({ snapshotReplay }: { snapshotReplay?: unknown }) => (
    <pre data-testid="metrics-replay">{JSON.stringify(snapshotReplay ?? null)}</pre>
  ),
}))

import App from './App'
import { emptyViewResponse, jsonResponse } from './test/timelineViewFixtures'

const VC = '11111111-1111-4111-8111-111111111111'

function tabNav(): HTMLElement {
  return document.querySelector('nav.tabs') as HTMLElement
}

describe('App: タイムラインからグラフへ', () => {
  beforeEach(() => {
    localStorage.clear()
    window.history.replaceState(null, '', '/#/timeline')
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.includes('/api/config')) {
          return Promise.resolve(
            jsonResponse({ event_retention_days: 7, metric_retention_days: 7, perf_sample_interval_seconds: 300 }),
          )
        }
        if (url.endsWith('/api/incident-timeline/view') && init?.method === 'POST') {
          return Promise.resolve(
            jsonResponse(
              emptyViewResponse({
                items: [
                  {
                    id: 'event:1',
                    kind: 'event',
                    timestamp_utc: '2026-03-22T00:10:00Z',
                    end_utc: '2026-03-22T00:14:00Z',
                    level: 'warning',
                    title: 'VmPoweredOffEvent',
                    entity_name: 'esx01',
                    vcenter_id: VC,
                    vcenter_name: 'vc-main',
                    count: 2,
                    ref: {},
                  },
                ],
                total_items: 1,
              }),
            ),
          )
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      }),
    )
  })
  afterEach(() => vi.unstubAllGlobals())

  it('行の「グラフで開く」でグラフのタブに移り、期間・vCenter・起点の目印が渡る', async () => {
    render(<App />)
    const row = await screen.findByRole('button', { name: /VmPoweredOffEvent/ })
    fireEvent.click(row)
    const region = await screen.findByRole('region', { name: /VmPoweredOffEvent の詳細/ })
    fireEvent.click(within(region).getByRole('button', { name: 'グラフで開く' }))
    await waitFor(() => expect(window.location.hash).toBe('#/metrics'))
    expect(within(tabNav()).getByRole('button', { name: 'グラフ' })).toHaveClass('active')
    const replay = JSON.parse((await screen.findByTestId('metrics-replay')).textContent!)
    expect(replay).toEqual({
      focus: {
        from: '2026-03-21T23:40:00.000Z',
        to: '2026-03-22T00:44:00.000Z',
        vcenterId: VC,
        markerUtc: '2026-03-22T00:10:00.000Z',
      },
      nonce: 1,
    })
  })
})
