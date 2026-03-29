import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { TimeZoneProvider } from '../../datetime/TimeZoneProvider'
import { DISPLAY_TIME_ZONE_STORAGE_KEY } from '../../datetime/timeZoneStorage'
import { ChatPanel } from './ChatPanel'

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderChat(onError: (e: string | null) => void = vi.fn()) {
  return render(
    <TimeZoneProvider>
      <ChatPanel onError={onError} />
    </TimeZoneProvider>,
  )
}

describe('ChatPanel', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.removeItem(DISPLAY_TIME_ZONE_STORAGE_KEY)
  })

  it('送信で POST /api/chat が呼ばれ、アシスタントの返答が表示される', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      if (url.endsWith('/api/chat') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body))
        expect(body.messages?.length).toBeGreaterThanOrEqual(1)
        expect(body.messages?.[body.messages.length - 1]?.role).toBe('user')
        return Promise.resolve(
          jsonResponse({ assistant_content: 'モック回答', error: null }),
        )
      }
      return Promise.resolve(new Response('not found', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderChat()
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })

    fireEvent.change(screen.getByPlaceholderText('質問を入力…'), {
      target: { value: 'テスト質問' },
    })
    fireEvent.click(screen.getByRole('button', { name: '送信' }))

    await waitFor(() => {
      expect(screen.getByText('モック回答')).toBeInTheDocument()
    })
    const chatPosts = fetchMock.mock.calls.filter(
      (c) => String(c[0]).endsWith('/api/chat') && (c[1] as RequestInit)?.method === 'POST',
    )
    expect(chatPosts.length).toBeGreaterThanOrEqual(1)
  })
})
