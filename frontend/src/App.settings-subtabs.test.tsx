/**
 * @vitest-environment happy-dom
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

/** 設定パネル内のサブタブ（TDD 受け入れ条件） */
const SETTINGS_SUBTAB_LABELS = [
  '一般',
  'vCenter',
  'スコアルール',
  'イベント種別ガイド',
  'アラート',
  'チャット',
] as const

const SETTINGS_SUBTAB_INTRO_MARKERS: Record<(typeof SETTINGS_SUBTAB_LABELS)[number], string> = {
  一般: 'このブラウザで使う基本設定を管理します',
  vCenter: 'パスワードは暗号化',
  スコアルール: '既存の取り込み済みイベントの再計算にも反映されます',
  イベント種別ガイド: '「対処が必要」をオンにすると',
  アラート: '判定対象になるのは有効化したルールだけです',
  チャット: '既定の行もここから編集・削除できます',
}

async function openSettingsSubtab(label: (typeof SETTINGS_SUBTAB_LABELS)[number]) {
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: '設定' }))
  const subNav = await screen.findByRole('navigation', { name: '設定' })
  fireEvent.click(within(subNav).getByRole('button', { name: label }))

  return await waitFor(() => {
    const intro = screen.getByText((content, element) => {
      return element?.tagName === 'P' && content.includes(SETTINGS_SUBTAB_INTRO_MARKERS[label])
    })
    const panel = intro.closest('.panel')
    expect(panel).toBeInTheDocument()
    return panel as HTMLElement
  })
}

describe('App 設定サブタブ', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  beforeEach(() => {
    vi.stubGlobal('localStorage', localStorageMock)
    localStorage.clear()
    vi.clearAllMocks()
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/api/config')) {
          return Promise.resolve(jsonResponse(emptyConfig))
        }
        if (
          url.includes('/api/vcenters') ||
          url.includes('/api/event-score-rules') ||
          url.includes('/api/event-type-guides') ||
          url.includes('/api/alerts/rules')
        ) {
          return Promise.resolve(jsonResponse([]))
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      }),
    )
  })

  it.each(SETTINGS_SUBTAB_LABELS)(
    '設定表示後「%s」ボタンに accessible name と装飾用 svg 1つがある',
    async (label) => {
      render(<App />)
      fireEvent.click(await screen.findByRole('button', { name: '設定' }))
      const subNav = await screen.findByRole('navigation', { name: '設定' })
      const btn = within(subNav).getByRole('button', { name: label })
      const svgs = btn.querySelectorAll('svg')
      expect(svgs.length).toBe(1)
      expect(svgs[0]).toHaveAttribute('aria-hidden', 'true')
      expect(svgs[0]).toHaveAttribute('focusable', 'false')
    },
  )

  it.each(SETTINGS_SUBTAB_LABELS)(
    '設定サブタブ「%s」は panel 直下の先頭に概要ヒントを表示する',
    async (label) => {
      const panel = await openSettingsSubtab(label)

      if (label === 'アラート') {
        expect(panel.firstElementChild).toHaveClass('alert-rules-panel-header')
        expect(panel.firstElementChild?.firstElementChild).toHaveClass('hint')
        expect(panel.firstElementChild?.firstElementChild?.tagName).toBe('P')
        return
      }

      expect(panel.firstElementChild).toHaveClass('hint')
      expect(panel.firstElementChild?.tagName).toBe('P')
    },
  )

  it('アラート設定サブタブは概要ヒントと新規ルール追加ボタンを同じヘッダー行に表示する', async () => {
    const panel = await openSettingsSubtab('アラート')
    const header = panel.firstElementChild as HTMLElement

    expect(header).toHaveClass('alert-rules-panel-header')
    expect(within(header).getByText((content, element) => {
      return element?.tagName === 'P' && content.includes(SETTINGS_SUBTAB_INTRO_MARKERS.アラート)
    })).toHaveClass('hint')
    expect(within(header).getByRole('button', { name: '新規ルール追加' })).toBeInTheDocument()
  })

  it('チャット設定サブタブは旧見出し「プロンプトスニペット」を表示しない', async () => {
    const panel = await openSettingsSubtab('チャット')

    expect(within(panel).queryByRole('heading', { level: 2, name: 'プロンプトスニペット' }))
      .not.toBeInTheDocument()
  })

  it('アラート設定サブタブは旧見出し「アラートルール設定」を表示しない', async () => {
    const panel = await openSettingsSubtab('アラート')

    expect(within(panel).queryByRole('heading', { level: 2, name: 'アラートルール設定' }))
      .not.toBeInTheDocument()
  })
})
