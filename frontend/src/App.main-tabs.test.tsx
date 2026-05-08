/**
 * @vitest-environment happy-dom
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./panels/metrics/MetricsPanel', () => ({
  MetricsPanel: ({
    onNavigateToTimeline,
  }: {
    onNavigateToTimeline?: (params: { vcenterId: string }) => void
  }) => {
    const [vcenterId, setVcenterId] = useState('')
    return (
      <div>
        <label>
          vCenter
          <select value={vcenterId} onChange={(e) => setVcenterId(e.target.value)}>
            <option value="">全て</option>
            <option value="550e8400-e29b-41d4-a716-446655440000">vc1</option>
          </select>
        </label>
        <button type="button" onClick={() => onNavigateToTimeline?.({ vcenterId })}>
          タイムラインへ移動
        </button>
      </div>
    )
  },
}))

import App from './App'

// 強制的な localStorage モック
const storage: Record<string, string> = {}
const localStorageMock = {
  getItem: vi.fn((key: string) => storage[key] || null),
  setItem: vi.fn((key: string, value: string) => { storage[key] = value }),
  clear: vi.fn(() => { for (const key in storage) delete storage[key] }),
  removeItem: vi.fn((key: string) => { delete storage[key] }),
  length: 0,
  key: vi.fn((index: number) => Object.keys(storage)[index] || null),
}
vi.stubGlobal('localStorage', localStorageMock)

const emptyConfig = {
  event_retention_days: 7,
  metric_retention_days: 7,
  perf_sample_interval_seconds: 300,
}

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function tabNav(): HTMLElement {
  const el = document.querySelector('nav.tabs')
  if (!el) throw new Error('nav.tabs not found')
  return el as HTMLElement
}

/** メインタブ: ラベルと装飾 SVG（計画どおり TDD の受け入れ条件） */
const MAIN_TAB_LABELS = [
  '概要',
  'イベント',
  'グラフ',
  'ダイジェスト',
  '通知履歴',
  'チャット',
  'タイムライン',
  '設定',
] as const

describe('App メインタブ', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  beforeEach(() => {
    localStorage.clear()
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/api/config')) {
          return Promise.resolve(jsonResponse(emptyConfig))
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      }),
    )
  })

  it.each(MAIN_TAB_LABELS)('「%s」ボタンに accessible name と装飾用 svg 1つがある', async (label) => {
    render(<App />)
    await waitFor(() => {
      expect(within(tabNav()).getByRole('button', { name: label })).toBeInTheDocument()
    })
    const btn = within(tabNav()).getByRole('button', { name: label })
    const svgs = btn.querySelectorAll('svg')
    expect(svgs.length).toBe(1)
    expect(svgs[0]).toHaveAttribute('aria-hidden', 'true')
    expect(svgs[0]).toHaveAttribute('focusable', 'false')
  })

  it('タイムラインタブを押すと TimelinePanel が表示される', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.includes('/api/config')) {
          return Promise.resolve(jsonResponse(emptyConfig))
        }
        if (url.endsWith('/api/vcenters')) {
          return Promise.resolve(jsonResponse([]))
        }
        if (url.endsWith('/api/dashboard/summary')) {
          return Promise.resolve(
            jsonResponse({
              vcenter_count: 0,
              events_last_24h: 0,
              notable_events_last_24h: 0,
              top_notable_events: [],
              high_cpu_hosts: [],
              high_mem_hosts: [],
              top_event_types_24h: [],
            }),
          )
        }
        if (url.endsWith('/api/incident-timeline') && init?.method === 'POST') {
          return Promise.resolve(jsonResponse({ columns: [] }))
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      }),
    )

    render(<App />)
    await waitFor(() => {
      expect(within(tabNav()).getByRole('button', { name: 'タイムライン' })).toBeInTheDocument()
    })

    within(tabNav()).getByRole('button', { name: 'タイムライン' }).click()

    await waitFor(() => {
      expect(
        screen.getByText('「タイムラインを生成」を押すと、指定期間のインシデント統合タイムラインを表示します。'),
      ).toBeInTheDocument()
    })
  })

  it('グラフタブに「タイムラインへ移動」操作が表示される', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/api/config')) {
          return Promise.resolve(jsonResponse(emptyConfig))
        }
        if (url.endsWith('/api/vcenters')) {
          return Promise.resolve(
            jsonResponse([{ id: '550e8400-e29b-41d4-a716-446655440000', name: 'vc1' }]),
          )
        }
        if (url.includes('/api/metrics/keys')) {
          return Promise.resolve(jsonResponse({ metric_keys: ['cpu.usage_pct'] }))
        }
        if (url.includes('/api/metrics?')) {
          return Promise.resolve(jsonResponse({ points: [], total: 0 }))
        }
        if (url.includes('/api/events/event-types')) {
          return Promise.resolve(jsonResponse({ event_types: [] }))
        }
        if (url.endsWith('/api/dashboard/summary')) {
          return Promise.resolve(
            jsonResponse({
              vcenter_count: 0,
              events_last_24h: 0,
              notable_events_last_24h: 0,
              top_notable_events: [],
              high_cpu_hosts: [],
              high_mem_hosts: [],
              top_event_types_24h: [],
            }),
          )
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      }),
    )

    render(<App />)
    await waitFor(() => {
      expect(within(tabNav()).getByRole('button', { name: 'グラフ' })).toBeInTheDocument()
    })
    within(tabNav()).getByRole('button', { name: 'グラフ' }).click()

    await waitFor(() => {
      expect(screen.getByLabelText('vCenter')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'タイムラインへ移動' })).toBeInTheDocument()
    })
  })

  it('グラフから「タイムラインへ移動」でタブ遷移し、vCenter 選択を引き継ぐ', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/api/config')) {
          return Promise.resolve(jsonResponse(emptyConfig))
        }
        if (url.endsWith('/api/vcenters')) {
          return Promise.resolve(
            jsonResponse([{ id: '550e8400-e29b-41d4-a716-446655440000', name: 'vc1' }]),
          )
        }
        if (url.includes('/api/metrics/keys')) {
          return Promise.resolve(jsonResponse({ metric_keys: ['cpu.usage_pct'] }))
        }
        if (url.includes('/api/metrics?')) {
          return Promise.resolve(jsonResponse({ points: [], total: 0 }))
        }
        if (url.includes('/api/events/event-types')) {
          return Promise.resolve(jsonResponse({ event_types: [] }))
        }
        if (url.endsWith('/api/dashboard/summary')) {
          return Promise.resolve(
            jsonResponse({
              vcenter_count: 0,
              events_last_24h: 0,
              notable_events_last_24h: 0,
              top_notable_events: [],
              high_cpu_hosts: [],
              high_mem_hosts: [],
              top_event_types_24h: [],
            }),
          )
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      }),
    )

    render(<App />)
    await waitFor(() => {
      expect(within(tabNav()).getByRole('button', { name: 'グラフ' })).toBeInTheDocument()
    })
    within(tabNav()).getByRole('button', { name: 'グラフ' }).click()

    await waitFor(() => {
      expect(screen.getByLabelText('vCenter')).toBeInTheDocument()
    })
    fireEvent.change(screen.getByLabelText('vCenter'), {
      target: { value: '550e8400-e29b-41d4-a716-446655440000' },
    })

    screen.getByRole('button', { name: 'タイムラインへ移動' }).click()

    await waitFor(() => {
      expect(
        screen.getByText('「タイムラインを生成」を押すと、指定期間のインシデント統合タイムラインを表示します。'),
      ).toBeInTheDocument()
    })
    expect(screen.getByLabelText('対象 vCenter')).toHaveValue('550e8400-e29b-41d4-a716-446655440000')
  })
})
