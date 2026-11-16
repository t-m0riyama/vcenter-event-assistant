/**
 * @vitest-environment happy-dom
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Me, Role } from './api/schemas'
import { AuthContext } from './auth/authContext'
import { roleAtLeast } from './auth/roles'

vi.mock('./panels/metrics/MetricsPanel', () => ({ MetricsPanel: () => <div /> }))
// チャットのタブへ渡された条件をそのまま表示するスタブ
const received = vi.hoisted(() => [] as { focus: Record<string, unknown>; nonce: number }[])
vi.mock('./panels/chat/ChatPanel', async () => {
  const React = await import('react')
  return {
    ChatPanel: ({ handoff, onHandoffApplied }: { handoff?: unknown; onHandoffApplied?: () => void }) => {
      // 本物のチャットと同じく、引き継ぎを受けたら適用したことを知らせる
      React.useEffect(() => {
        if (!handoff) return
        received.push(handoff as (typeof received)[number])
        onHandoffApplied?.()
      }, [handoff, onHandoffApplied])
      return <pre data-testid="chat-handoff">{JSON.stringify(handoff ?? null)}</pre>
    },
  }
})

import App from './App'
import { emptyViewResponse, jsonResponse } from './test/timelineViewFixtures'

function tabNav(): HTMLElement {
  return document.querySelector('nav.tabs') as HTMLElement
}

function renderAs(role: Role) {
  const me: Me = {
    auth_enabled: true,
    username: `${role}-user`,
    display_name: null,
    role,
    realm: 'local',
    can_change_password: true,
  }
  return render(
    <AuthContext.Provider
      value={{ me, hasRole: (r) => roleAtLeast(me.role, r), logout: async () => {}, refresh: async () => {} }}
    >
      <App />
    </AuthContext.Provider>,
  )
}

describe('App: タイムラインからチャットへ', () => {
  beforeEach(() => {
    localStorage.clear()
    received.length = 0
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
          return Promise.resolve(jsonResponse(emptyViewResponse()))
        }
        return Promise.resolve(jsonResponse([]))
      }),
    )
  })
  afterEach(() => vi.unstubAllGlobals())

  it('operator は「この範囲をチャットで分析」でチャットのタブに移り、期間と vCenter だけが渡る', async () => {
    renderAs('operator')
    const button = await screen.findByRole('button', { name: 'この範囲をチャットで分析' })
    fireEvent.click(button)
    await waitFor(() => expect(window.location.hash).toBe('#/chat'))
    expect(tabNav().querySelector('button.active')).toHaveTextContent('チャット')
    // 適用したら App が引き継ぎを消す（作り直されても当て直さない）
    await waitFor(() => expect(screen.getByTestId('chat-handoff').textContent).toBe('null'))
  })

  it('渡す条件は期間と vCenter と、絞り込みを引き継がないことの印だけ。2 回続けて押すと、独立した連番で 2 回渡る', async () => {
    renderAs('operator')
    const press = async () => {
      fireEvent.click(await screen.findByRole('button', { name: 'この範囲をチャットで分析' }))
      await waitFor(() => expect(window.location.hash).toBe('#/chat'))
      fireEvent.click(within(tabNav()).getByRole('button', { name: 'タイムライン' }))
      await waitFor(() => expect(window.location.hash).toContain('#/timeline'))
    }
    await press()
    await press()
    expect(received.map((r) => r.nonce)).toEqual([1, 2])
    expect(Object.keys(received[0].focus).sort()).toEqual(['from', 'fromSavedSnapshot', 'narrowedBy', 'to', 'vcenterId'])
    expect(received[0].focus.vcenterId).toBeNull()
    expect(received[0].focus.narrowedBy).toEqual([])
    expect(received[0].focus.fromSavedSnapshot).toBe(false)
  })

  it('viewer にはチャットのタブも「この範囲をチャットで分析」も出さない', async () => {
    renderAs('viewer')
    await screen.findByText(/読み込んだ期間/)
    expect(screen.queryByRole('button', { name: 'この範囲をチャットで分析' })).not.toBeInTheDocument()
  })
})
