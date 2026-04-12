/**
 * @vitest-environment happy-dom
 */
import { fireEvent, render, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

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

function mainTabNav(): HTMLElement {
  const el = document.querySelector('nav.tabs')
  if (!el) throw new Error('nav.tabs not found')
  return el as HTMLElement
}

function settingsSubNav(): HTMLElement {
  const el = document.querySelector('nav.settings-subtabs')
  if (!el) throw new Error('nav.settings-subtabs not found')
  return el as HTMLElement
}

/** 設定パネル内のサブタブ（TDD 受け入れ条件） */
const SETTINGS_SUBTAB_LABELS = [
  '一般',
  'vCenter',
  'スコアルール',
  'イベント種別ガイド',
  'チャット',
] as const

describe('App 設定サブタブ', () => {
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

  it.each(SETTINGS_SUBTAB_LABELS)(
    '設定表示後「%s」ボタンに accessible name と装飾用 svg 1つがある',
    async (label) => {
      render(<App />)
      await waitFor(() => {
        expect(within(mainTabNav()).getByRole('button', { name: '設定' })).toBeInTheDocument()
      })
      fireEvent.click(within(mainTabNav()).getByRole('button', { name: '設定' }))
      await waitFor(() => {
        expect(within(settingsSubNav()).getByRole('button', { name: label })).toBeInTheDocument()
      })
      const btn = within(settingsSubNav()).getByRole('button', { name: label })
      const svgs = btn.querySelectorAll('svg')
      expect(svgs.length).toBe(1)
      expect(svgs[0]).toHaveAttribute('aria-hidden', 'true')
      expect(svgs[0]).toHaveAttribute('focusable', 'false')
    },
  )
})
