import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'

const emptySummary = {
  vcenter_count: 0,
  events_last_24h: 0,
  notable_events_last_24h: 0,
  top_notable_events: [] as unknown[],
  high_cpu_hosts: [] as unknown[],
  top_event_types_24h: [] as unknown[],
}

const emptyConfig = {
  event_retention_days: 7,
  metric_retention_days: 7,
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

describe('App error banner', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows role=alert when dashboard summary fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/api/config')) {
          return Promise.resolve(jsonResponse(emptyConfig))
        }
        return Promise.resolve(new Response('bad', { status: 500 }))
      }),
    )
    render(<App />)
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('500 bad')
    })
  })

  it('shows role=alert when events list fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/api/config')) {
          return Promise.resolve(jsonResponse(emptyConfig))
        }
        if (url.includes('/api/dashboard/summary')) {
          return Promise.resolve(jsonResponse(emptySummary))
        }
        if (url.includes('/api/events')) {
          return Promise.resolve(new Response('no', { status: 502 }))
        }
        return Promise.resolve(new Response('n', { status: 404 }))
      }),
    )
    render(<App />)
    await waitFor(() => {
      const [h] = screen.getAllByRole('heading', {
        name: '高 CPU ホスト（直近24h サンプル上位）',
      })
      expect(h).toBeInTheDocument()
    })
    fireEvent.click(within(tabNav()).getByRole('button', { name: 'イベント' }))
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('502 no')
    })
  })

  it('shows role=alert when vcenters list fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/api/config')) {
          return Promise.resolve(jsonResponse(emptyConfig))
        }
        if (url.includes('/api/dashboard/summary')) {
          return Promise.resolve(jsonResponse(emptySummary))
        }
        if (url.includes('/api/vcenters')) {
          return Promise.resolve(new Response('vc fail', { status: 503 }))
        }
        return Promise.resolve(new Response('n', { status: 404 }))
      }),
    )
    render(<App />)
    await waitFor(() => {
      const [h] = screen.getAllByRole('heading', {
        name: '高 CPU ホスト（直近24h サンプル上位）',
      })
      expect(h).toBeInTheDocument()
    })
    fireEvent.click(within(tabNav()).getByRole('button', { name: '設定' }))
    fireEvent.click(
      within(document.querySelector('nav.settings-subtabs') as HTMLElement).getByRole(
        'button',
        { name: 'vCenter' },
      ),
    )
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('503 vc fail')
    })
  })

  it('shows role=alert when metrics series fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/api/config')) {
          return Promise.resolve(jsonResponse(emptyConfig))
        }
        if (url.includes('/api/dashboard/summary')) {
          return Promise.resolve(jsonResponse(emptySummary))
        }
        if (url.includes('/api/vcenters')) {
          return Promise.resolve(jsonResponse([]))
        }
        if (url.includes('/api/metrics')) {
          return Promise.resolve(new Response('m err', { status: 500 }))
        }
        return Promise.resolve(new Response('n', { status: 404 }))
      }),
    )
    render(<App />)
    await waitFor(() => {
      const [h] = screen.getAllByRole('heading', {
        name: '高 CPU ホスト（直近24h サンプル上位）',
      })
      expect(h).toBeInTheDocument()
    })
    fireEvent.click(within(tabNav()).getByRole('button', { name: 'メトリクス' }))
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('500 m err')
    })
  })
})
