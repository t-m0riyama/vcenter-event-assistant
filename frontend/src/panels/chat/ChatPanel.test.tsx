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

function messagesListElement(): HTMLElement {
  const el = document.querySelector('ul.chat-panel__messages')
  if (!el) throw new Error('ul.chat-panel__messages が見つかりません')
  return el as HTMLElement
}

/**
 * 会話リストのスクロール寸法をテスト用に上書きする。
 * `scrollHeight` は可変（応答後にコンテンツが伸びた想定で `setScrollHeight` を呼ぶ）。
 */
function attachScrollableMessagesListMock(
  el: HTMLElement,
  init: {
    scrollHeight: number
    clientHeight: number
    scrollTop: number
  },
  options?: { onScrollTopSet?: (value: number) => void },
): { getScrollTop: () => number; setScrollHeight: (h: number) => void } {
  let scrollTop = init.scrollTop
  let scrollHeight = init.scrollHeight
  const clientHeight = init.clientHeight

  Object.defineProperty(el, 'clientHeight', {
    configurable: true,
    get: () => clientHeight,
  })
  Object.defineProperty(el, 'scrollHeight', {
    configurable: true,
    get: () => scrollHeight,
  })
  Object.defineProperty(el, 'scrollTop', {
    configurable: true,
    get: () => scrollTop,
    set(v: number) {
      options?.onScrollTopSet?.(v)
      scrollTop = v
    },
  })

  return {
    getScrollTop: () => scrollTop,
    setScrollHeight: (h: number) => {
      scrollHeight = h
    },
  }
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

  it('CPU 使用率のチェックをオンにすると POST 本文に include_period_metrics_cpu が含まれる', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      if (url.endsWith('/api/chat') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as { include_period_metrics_cpu?: boolean }
        expect(body.include_period_metrics_cpu).toBe(true)
        return Promise.resolve(jsonResponse({ assistant_content: 'x', error: null }))
      }
      return Promise.resolve(new Response('not found', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderChat()
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })

    fireEvent.click(screen.getByRole('checkbox', { name: /^CPU 使用率$/ }))
    fireEvent.change(screen.getByPlaceholderText('質問を入力…'), {
      target: { value: 'q' },
    })
    fireEvent.click(screen.getByRole('button', { name: '送信' }))

    await waitFor(() => {
      const posts = fetchMock.mock.calls.filter(
        (c) => String(c[0]).endsWith('/api/chat') && (c[1] as RequestInit)?.method === 'POST',
      )
      expect(posts.length).toBeGreaterThanOrEqual(1)
    })
  })

  describe('メッセージリストの追従スクロール', () => {
    it('最下部付近にいるとき LLM 応答後に最下端へスクロールする', async () => {
      let bumpScrollHeight: ((h: number) => void) | null = null

      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.endsWith('/api/vcenters')) {
          return Promise.resolve(jsonResponse([]))
        }
        if (url.endsWith('/api/chat') && init?.method === 'POST') {
          bumpScrollHeight?.(1200)
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

      const listEl = messagesListElement()
      const { getScrollTop, setScrollHeight } = attachScrollableMessagesListMock(listEl, {
        scrollHeight: 1000,
        clientHeight: 200,
        scrollTop: 800,
      })
      bumpScrollHeight = setScrollHeight
      fireEvent.scroll(listEl)

      fireEvent.change(screen.getByPlaceholderText('質問を入力…'), {
        target: { value: 'テスト質問' },
      })
      fireEvent.click(screen.getByRole('button', { name: '送信' }))

      await waitFor(() => {
        expect(screen.getByText('モック回答')).toBeInTheDocument()
      })

      expect(getScrollTop()).toBe(1000)
    })

    it('上にスクロールして履歴を見ているときは LLM 応答後もスクロール位置を変えない', async () => {
      let bumpScrollHeight: ((h: number) => void) | null = null
      const assignedScrollTops: number[] = []

      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.endsWith('/api/vcenters')) {
          return Promise.resolve(jsonResponse([]))
        }
        if (url.endsWith('/api/chat') && init?.method === 'POST') {
          bumpScrollHeight?.(1200)
          return Promise.resolve(
            jsonResponse({ assistant_content: '下の返答', error: null }),
          )
        }
        return Promise.resolve(new Response('not found', { status: 404 }))
      })
      vi.stubGlobal('fetch', fetchMock)

      renderChat()
      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalled()
      })

      const listEl = messagesListElement()
      const { getScrollTop, setScrollHeight } = attachScrollableMessagesListMock(
        listEl,
        {
          scrollHeight: 1000,
          clientHeight: 200,
          scrollTop: 0,
        },
        {
          onScrollTopSet: (v) => {
            assignedScrollTops.push(v)
          },
        },
      )
      bumpScrollHeight = setScrollHeight
      fireEvent.scroll(listEl)

      fireEvent.change(screen.getByPlaceholderText('質問を入力…'), {
        target: { value: '質問' },
      })
      fireEvent.click(screen.getByRole('button', { name: '送信' }))

      await waitFor(() => {
        expect(screen.getByText('下の返答')).toBeInTheDocument()
      })

      expect(getScrollTop()).toBe(0)
      const maxScroll = 1200 - 200
      expect(assignedScrollTops).not.toContain(maxScroll)
    })
  })
})
