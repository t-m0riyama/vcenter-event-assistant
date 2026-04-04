import { render, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'

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

/** メイン6タブ: ラベルと装飾 SVG（計画どおり TDD の受け入れ条件） */
const MAIN_TAB_LABELS = ['概要', 'イベント', 'グラフ', 'ダイジェスト', 'チャット', '設定'] as const

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
})
