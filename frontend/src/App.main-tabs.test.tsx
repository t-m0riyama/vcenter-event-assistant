/**
 * @vitest-environment happy-dom
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./panels/metrics/MetricsPanel', () => ({
  MetricsPanel: () => (
    <div>
      <label>
        vCenter
        <select defaultValue="">
          <option value="">全て</option>
        </select>
      </label>
    </div>
  ),
}))

import App from './App'
import { emptyViewResponse } from './test/timelineViewFixtures'

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
  'ログ',
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
        if (url.endsWith('/api/incident-timeline/view') && init?.method === 'POST') {
          return Promise.resolve(jsonResponse(emptyViewResponse()))
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      }),
    )

    render(<App />)
    await waitFor(() => {
      expect(within(tabNav()).getByRole('button', { name: 'タイムライン' })).toBeInTheDocument()
    })

    within(tabNav()).getByRole('button', { name: 'タイムライン' }).click()

    // 開くと「生成」を押さずに自動で読み込み、条件が URL に出る
    await waitFor(() => {
      expect(screen.getByText('この期間に出来事はありません。')).toBeInTheDocument()
    })
    expect(window.location.hash).toBe('#/timeline?range=1h')

    // 別のタブを開いても、タイムラインは非表示のまま URL を奪わない
    within(tabNav()).getByRole('button', { name: 'イベント' }).click()
    await waitFor(() => expect(window.location.hash).toBe('#/events'))
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(window.location.hash).toBe('#/events')

    // 戻ると、持っている条件が URL に戻る
    within(tabNav()).getByRole('button', { name: 'タイムライン' }).click()
    await waitFor(() => expect(window.location.hash).toBe('#/timeline?range=1h'))
  })
})
