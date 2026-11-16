/**
 * @vitest-environment happy-dom
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Me, Role } from './api/schemas'
import { AuthContext } from './auth/authContext'
import { roleAtLeast } from './auth/roles'

vi.mock('./panels/metrics/MetricsPanel', () => ({ MetricsPanel: () => <div /> }))
// チャットのタブへ渡された条件をそのまま表示するスタブ
vi.mock('./panels/chat/ChatPanel', () => ({
  ChatPanel: ({ handoff }: { handoff?: unknown }) => (
    <pre data-testid="chat-handoff">{JSON.stringify(handoff ?? null)}</pre>
  ),
}))

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
    const handoff = JSON.parse((await screen.findByTestId('chat-handoff')).textContent!)
    expect(Object.keys(handoff.focus).sort()).toEqual(['from', 'to', 'vcenterId'])
    expect(handoff.focus.vcenterId).toBeNull()
    expect(handoff.nonce).toBe(1)
  })

  it('viewer にはチャットのタブも「この範囲をチャットで分析」も出さない', async () => {
    renderAs('viewer')
    await screen.findByText(/読み込んだ期間/)
    expect(screen.queryByRole('button', { name: 'この範囲をチャットで分析' })).not.toBeInTheDocument()
  })
})
