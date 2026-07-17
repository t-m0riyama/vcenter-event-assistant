/**
 * @vitest-environment happy-dom
 */
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import App from './App'

const storage: Record<string, string> = {}
vi.stubGlobal('localStorage', {
  getItem: vi.fn((key: string) => storage[key] || null),
  setItem: vi.fn((key: string, value: string) => { storage[key] = value }),
  clear: vi.fn(() => { for (const key in storage) delete storage[key] }),
  removeItem: vi.fn((key: string) => { delete storage[key] }),
  length: 0,
  key: vi.fn((index: number) => Object.keys(storage)[index] || null),
})

function stubFetch(attention: { notable_events_last_24h: number; firing_alerts: number } | null) {
  vi.stubGlobal('fetch', vi.fn((input) => {
    const url = String(input)
    if (url.includes('/api/config')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ event_retention_days: 7, metric_retention_days: 7 }),
      })
    }
    if (url.includes('/api/dashboard/attention') && attention) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(attention) })
    }
    return Promise.resolve({ ok: false })
  }))
}

describe('タブのアテンションドット', () => {
  it('要注意イベントと firing アラートがあるとき、概要・通知履歴タブにドットが出る', async () => {
    stubFetch({ notable_events_last_24h: 3, firing_alerts: 1 })
    render(<App />)
    await waitFor(() => {
      expect(screen.getAllByTitle('要注意の項目があります')).toHaveLength(2)
    })
  })

  it('カウントが 0 のときはドットを出さない', async () => {
    stubFetch({ notable_events_last_24h: 0, firing_alerts: 0 })
    render(<App />)
    await screen.findByRole('button', { name: /使い方を表示/ })
    expect(screen.queryByTitle('要注意の項目があります')).not.toBeInTheDocument()
  })

  it('attention API が失敗してもアプリは通常どおり表示される', async () => {
    stubFetch(null)
    render(<App />)
    expect(await screen.findByRole('button', { name: /使い方を表示/ })).toBeInTheDocument()
    expect(screen.queryByTitle('要注意の項目があります')).not.toBeInTheDocument()
  })
})
