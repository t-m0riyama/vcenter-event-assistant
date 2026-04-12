/**
 * @vitest-environment happy-dom
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import App from './App'

// localStorage のモックを強制適用（happy-dom であっても getItem/setItem 等が不足する場合があるため）
const storage: Record<string, string> = {}
vi.stubGlobal('localStorage', {
  getItem: vi.fn((key: string) => storage[key] || null),
  setItem: vi.fn((key: string, value: string) => { storage[key] = value }),
  clear: vi.fn(() => { for (const key in storage) delete storage[key] }),
  removeItem: vi.fn((key: string) => { delete storage[key] }),
  length: 0,
  key: vi.fn((index: number) => Object.keys(storage)[index] || null),
})

describe('App 簡易ヘルプ機能', () => {
  beforeEach(() => {
    // localStorage.clear() // エラー回避のため一旦コメントアウト（モック側で初期化されるか、副作用を許容）
    vi.stubGlobal('fetch', vi.fn((input) => {
      const url = String(input)
      if (url.includes('/api/config')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ event_retention_days: 7, metric_retention_days: 7 })
        })
      }
      return Promise.resolve({ ok: false })
    }))
  })

  it('「使い方を表示」ボタンが表示されている', async () => {
    render(<App />)
    const button = await screen.findByRole('button', { name: /使い方を表示/ })
    expect(button).toBeInTheDocument()
  })

  it('初期状態ではヘルプエリアが表示されていない', async () => {
    render(<App />)
    // 「【概要】」というテキストが含まれる要素がないことを確認
    expect(screen.queryByText(/【概要】/)).not.toBeInTheDocument()
  })

  it('ボタンクリックでヘルプエリアが表示される', async () => {
    render(<App />)
    const button = await screen.findByRole('button', { name: /使い方を表示/ })
    fireEvent.click(button)
    // ヘルプが表示されるのを待つ
    expect(await screen.findByText(/【概要】/)).toBeInTheDocument()
  })

  it('タブを切り替えた際にヘルプエリアが自動的に閉じる', async () => {
    render(<App />)
    const helpBtn = await screen.findByRole('button', { name: /使い方を表示/ })
    fireEvent.click(helpBtn)
    expect(await screen.findByText(/【概要】/)).toBeInTheDocument()

    // 「イベント」タブに切り替え
    const eventTab = screen.getByRole('button', { name: /イベント/ })
    fireEvent.click(eventTab)

    // ヘルプが閉じている（要素が消えている）ことを確認
    await waitFor(() => {
      expect(screen.queryByText(/【概要】/)).not.toBeInTheDocument()
    })
  })
})
