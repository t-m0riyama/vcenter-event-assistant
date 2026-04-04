import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import '../../App.css'
import { TimeZoneProvider } from '../../datetime/TimeZoneProvider'
import { DISPLAY_TIME_ZONE_STORAGE_KEY } from '../../datetime/timeZoneStorage'
import { ChatCustomSamplePromptsProvider } from '../../preferences/ChatCustomSamplePromptsProvider'
import {
  CHAT_ASSISTANT_MESSAGE_LIST_TOP_MARGIN_PX,
  computeScrollTopToShowChildAtListTop,
} from './chatMessagesListScroll'
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
      <ChatCustomSamplePromptsProvider>
        <ChatPanel onError={onError} />
      </ChatCustomSamplePromptsProvider>
    </TimeZoneProvider>,
  )
}

function messagesListElement(): HTMLElement {
  const el = document.querySelector('ul.chat-panel__messages')
  if (!el) throw new Error('ul.chat-panel__messages が見つかりません')
  return el as HTMLElement
}

/** チャットコンポーザー周りのスタイルが意図どおりか（happy-dom の getComputedStyle が弱いためソースを検査する） */
function readAppCss(): string {
  const dir = path.dirname(fileURLToPath(import.meta.url))
  return readFileSync(path.join(dir, '../../App.css'), 'utf8')
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

  it('アシスタント応答の GFM テーブルを描画する', async () => {
    const tableMd = '|列A|列B|\n|---|---|\n|1|2|'
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      if (url.endsWith('/api/chat') && init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ assistant_content: tableMd, error: null }))
      }
      return Promise.resolve(new Response('not found', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderChat()
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())

    fireEvent.change(screen.getByPlaceholderText('質問を入力…'), {
      target: { value: '表を出して' },
    })
    fireEvent.click(screen.getByRole('button', { name: '送信' }))

    await waitFor(() => {
      expect(screen.getByRole('table')).toBeInTheDocument()
    })
    expect(screen.getByRole('columnheader', { name: '列A' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: '2' })).toBeInTheDocument()
  })

  it('コンポーザーは入力欄ラッパーが先・送信ボタンが後の子要素順になる', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      return Promise.resolve(new Response('not found', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    const { container } = renderChat()
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })

    const composer = container.querySelector('.chat-panel__composer')
    expect(composer).toBeInstanceOf(HTMLElement)
    const kids = composer ? Array.from(composer.children) : []
    expect(kids.length).toBe(2)
    expect(kids[0].className).toMatch(/chat-panel__composer-field/)
    expect(kids[1]).toBeInstanceOf(HTMLButtonElement)
    expect((kids[1] as HTMLButtonElement).getAttribute('aria-label')).toBe('送信')
  })

  it('App.css でコンポーザーが横並び（flex-direction: row）になる', () => {
    const css = readAppCss()
    expect(css).toMatch(/\.chat-panel__composer\s*\{[^}]*flex-direction:\s*row/s)
  })

  it('App.css の狭い画面メディアクエリ内でコンポーザーが縦積みになる', () => {
    const css = readAppCss()
    const mediaStart = css.indexOf('@media (max-width: 768px)')
    expect(mediaStart).toBeGreaterThanOrEqual(0)
    expect(css.slice(mediaStart)).toMatch(/\.chat-panel__composer[\s\S]*?flex-direction:\s*column/)
  })

  it('App.css でコンポーザー内 textarea の上限幅が 560px より広い', () => {
    const css = readAppCss()
    expect(css).toMatch(/\.chat-panel__composer\s+textarea\s*\{[^}]*max-width:\s*min\(\s*100%\s*,\s*960px\s*\)/s)
  })

  it('メッセージ入力 textarea は .chat-panel__composer-field 内にある', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      return Promise.resolve(new Response('not found', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    const { container } = renderChat()
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })

    const field = container.querySelector('.chat-panel__composer-field')
    expect(field).toBeInstanceOf(HTMLElement)
    expect(field?.querySelector('textarea[placeholder="質問を入力…"]')).toBeInstanceOf(
      HTMLTextAreaElement,
    )
  })

  it('サンプルを複数選択して下書きに挿入すると定義順で \\n\\n 連結される', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      return Promise.resolve(new Response('not found', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderChat()
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })

    fireEvent.click(screen.getByRole('button', { name: 'サンプル「メトリクス併用」' }))
    fireEvent.click(screen.getByRole('button', { name: 'サンプル「期間の要約」' }))
    fireEvent.click(screen.getByRole('button', { name: '下書きに挿入' }))

    const ta = screen.getByPlaceholderText('質問を入力…') as HTMLTextAreaElement
    expect(ta.value).toContain('この期間のイベントと傾向を')
    expect(ta.value).toContain('期間メトリクス（CPU・メモリ等）')
    expect(ta.value.indexOf('この期間のイベントと傾向を')).toBeLessThan(
      ta.value.indexOf('期間メトリクス（CPU・メモリ等）'),
    )

    expect(screen.getByRole('button', { name: 'サンプル「期間の要約」' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
  })

  it('サンプル挿入は既存下書きの末尾に追記する', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      return Promise.resolve(new Response('not found', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderChat()
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })

    fireEvent.change(screen.getByPlaceholderText('質問を入力…'), { target: { value: '既存' } })
    fireEvent.click(screen.getByRole('button', { name: 'サンプル「期間の要約」' }))
    fireEvent.click(screen.getByRole('button', { name: '下書きに挿入' }))

    const ta = screen.getByPlaceholderText('質問を入力…') as HTMLTextAreaElement
    expect(ta.value.startsWith('既存')).toBe(true)
    expect(ta.value).toContain('この期間のイベントと傾向を')
  })

  it('送信中はサンプルトグルと下書きに挿入が無効になる', async () => {
    let releasePost: (() => void) | undefined
    const postPromise = new Promise<Response>((resolve) => {
      releasePost = () => {
        resolve(jsonResponse({ assistant_content: '遅延回答', error: null }))
      }
    })

    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      if (url.endsWith('/api/chat') && init?.method === 'POST') {
        return postPromise
      }
      return Promise.resolve(new Response('not found', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderChat()
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })

    fireEvent.change(screen.getByPlaceholderText('質問を入力…'), { target: { value: 'q' } })
    fireEvent.click(screen.getByRole('button', { name: '送信' }))

    await waitFor(() => {
      expect(screen.getByText('応答を生成しています…')).toBeInTheDocument()
    })

    expect(screen.getByRole('button', { name: '下書きに挿入' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'サンプル「期間の要約」' })).toBeDisabled()

    releasePost?.()
    await waitFor(() => {
      expect(screen.getByText('遅延回答')).toBeInTheDocument()
    })
  })

  it('回答をコピーでクリップボードに該当アシスタント本文が入る', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', {
      ...navigator,
      clipboard: { writeText },
    })

    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      if (url.endsWith('/api/chat') && init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ assistant_content: '最終回答', error: null }))
      }
      return Promise.resolve(new Response('not found', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderChat()
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })

    fireEvent.change(screen.getByPlaceholderText('質問を入力…'), {
      target: { value: 'q' },
    })
    fireEvent.click(screen.getByRole('button', { name: '送信' }))
    await waitFor(() => {
      expect(screen.getByText('最終回答')).toBeInTheDocument()
    })

    const conversation = screen.getByRole('list', { name: '会話' })
    fireEvent.click(within(conversation).getByRole('button', { name: '回答をコピー' }))

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith('最終回答')
    })
  })

  it('アシスタントが2件のときそれぞれの回答をコピーできる', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', {
      ...navigator,
      clipboard: { writeText },
    })

    let postCount = 0
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      if (url.endsWith('/api/chat') && init?.method === 'POST') {
        postCount += 1
        const body = JSON.parse(String(init.body)) as { messages?: { role: string; content: string }[] }
        const lastUser = [...(body.messages ?? [])].reverse().find((m) => m.role === 'user')
        if (postCount === 1) {
          expect(lastUser?.content).toBe('一問目')
          return Promise.resolve(jsonResponse({ assistant_content: '回答A', error: null }))
        }
        expect(lastUser?.content).toBe('二問目')
        return Promise.resolve(jsonResponse({ assistant_content: '回答B', error: null }))
      }
      return Promise.resolve(new Response('not found', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderChat()
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })

    const ta = screen.getByPlaceholderText('質問を入力…')
    fireEvent.change(ta, { target: { value: '一問目' } })
    fireEvent.click(screen.getByRole('button', { name: '送信' }))
    await waitFor(() => {
      expect(screen.getByText('回答A')).toBeInTheDocument()
    })

    fireEvent.change(ta, { target: { value: '二問目' } })
    fireEvent.click(screen.getByRole('button', { name: '送信' }))
    await waitFor(() => {
      expect(screen.getByText('回答B')).toBeInTheDocument()
    })

    const conversation = screen.getByRole('list', { name: '会話' })
    const copyButtons = within(conversation).getAllByRole('button', { name: '回答をコピー' })
    expect(copyButtons.length).toBe(2)

    const firstAssistantLi = screen.getByText('回答A').closest('li')
    expect(firstAssistantLi).toBeInstanceOf(HTMLElement)
    fireEvent.click(
      within(firstAssistantLi as HTMLElement).getByRole('button', { name: '回答をコピー' }),
    )
    await waitFor(() => {
      expect(writeText).toHaveBeenLastCalledWith('回答A')
    })

    const secondAssistantLi = screen.getByText('回答B').closest('li')
    expect(secondAssistantLi).toBeInstanceOf(HTMLElement)
    fireEvent.click(
      within(secondAssistantLi as HTMLElement).getByRole('button', { name: '回答をコピー' }),
    )
    await waitFor(() => {
      expect(writeText).toHaveBeenLastCalledWith('回答B')
    })
  })

  it('Enter キーで送信される', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      if (url.endsWith('/api/chat') && init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ assistant_content: 'ok', error: null }))
      }
      return Promise.resolve(new Response('not found', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderChat()
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })

    const ta = screen.getByPlaceholderText('質問を入力…')
    fireEvent.change(ta, { target: { value: 'enter で送る' } })
    fireEvent.keyDown(ta, { key: 'Enter', code: 'Enter', shiftKey: false })

    await waitFor(() => {
      expect(screen.getByText('ok')).toBeInTheDocument()
    })
  })

  it('IME 確定中は Enter で送信しない', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      if (url.endsWith('/api/chat') && init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ assistant_content: 'no', error: null }))
      }
      return Promise.resolve(new Response('not found', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderChat()
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })

    const ta = screen.getByPlaceholderText('質問を入力…')
    fireEvent.change(ta, { target: { value: '変換中' } })
    fireEvent.compositionStart(ta)

    const evt = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
    Object.defineProperty(evt, 'isComposing', { value: true })
    ta.dispatchEvent(evt)

    const posts = fetchMock.mock.calls.filter(
      (c) => String(c[0]).endsWith('/api/chat') && (c[1] as RequestInit)?.method === 'POST',
    )
    expect(posts.length).toBe(0)

    fireEvent.compositionEnd(ta)
  })

  it('Shift+Enter では送信せず改行だけされる', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      void init
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      return Promise.resolve(new Response('not found', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderChat()
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })

    const ta = screen.getByPlaceholderText('質問を入力…')
    fireEvent.change(ta, { target: { value: 'line1' } })
    fireEvent.keyDown(ta, { key: 'Enter', code: 'Enter', shiftKey: true })

    await waitFor(() => {
      expect(ta).toHaveValue('line1\n')
    })

    const posts = fetchMock.mock.calls.filter(
      (c) => String(c[0]).endsWith('/api/chat') && (c[1] as RequestInit)?.method === 'POST',
    )
    expect(posts.length).toBe(0)
  })

  it('会話をクリアで確認後にメッセージが空になる', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      if (url.endsWith('/api/chat') && init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ assistant_content: 'a', error: null }))
      }
      return Promise.resolve(new Response('not found', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderChat()
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })

    fireEvent.change(screen.getByPlaceholderText('質問を入力…'), {
      target: { value: 'q' },
    })
    fireEvent.click(screen.getByRole('button', { name: '送信' }))
    await waitFor(() => {
      expect(screen.getByText('a')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: '会話をクリア' }))

    expect(confirmSpy).toHaveBeenCalled()
    expect(screen.queryByText('a')).not.toBeInTheDocument()
    expect(screen.queryByText('q')).not.toBeInTheDocument()

    confirmSpy.mockRestore()
  })

  it('送信中は会話リストにプレースホルダが表示され ul に aria-busy が付く', async () => {
    let resolveChat!: (r: Response) => void
    const chatPromise = new Promise<Response>((res) => {
      resolveChat = res
    })

    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      if (url.endsWith('/api/chat') && init?.method === 'POST') {
        return chatPromise
      }
      return Promise.resolve(new Response('not found', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderChat()
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })

    fireEvent.change(screen.getByPlaceholderText('質問を入力…'), {
      target: { value: '保留テスト' },
    })
    fireEvent.click(screen.getByRole('button', { name: '送信' }))

    await waitFor(() => {
      expect(screen.getByText('応答を生成しています…')).toBeInTheDocument()
    })
    const sendBtn = screen.getByRole('button', { name: '送信中' })
    expect(sendBtn).toBeDisabled()
    expect(sendBtn).toHaveAttribute('aria-busy', 'true')
    expect(messagesListElement()).toHaveAttribute('aria-busy', 'true')

    resolveChat(jsonResponse({ assistant_content: '完了', error: null }))

    await waitFor(() => {
      expect(screen.queryByText('応答を生成しています…')).not.toBeInTheDocument()
    })
    expect(messagesListElement()).toHaveAttribute('aria-busy', 'false')
    const sendAfter = screen.getByRole('button', { name: '送信' })
    expect(sendAfter.getAttribute('aria-busy')).not.toBe('true')
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
    beforeAll(() => {
      const style = document.createElement('style')
      style.dataset.testChatScroll = '1'
      style.textContent = `.chat-panel__messages { position: relative; }`
      document.head.appendChild(style)
    })

    afterAll(() => {
      document.querySelector('style[data-test-chat-scroll="1"]')?.remove()
    })

    it('最下部付近にいるとき LLM 応答後に最新アシスタント先頭付近までスクロールする', async () => {
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

      const lastAssistant = screen.getByText('モック回答').closest('li')
      expect(lastAssistant).toBeInstanceOf(HTMLElement)
      const childTop = (lastAssistant as HTMLElement).offsetTop
      expect(getScrollTop()).toBe(
        computeScrollTopToShowChildAtListTop({
          childOffsetTop: childTop,
          scrollHeight: 1200,
          clientHeight: 200,
          marginPx: CHAT_ASSISTANT_MESSAGE_LIST_TOP_MARGIN_PX,
        }),
      )
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
      const lastAssistant = screen.getByText('下の返答').closest('li')
      expect(lastAssistant).toBeInstanceOf(HTMLElement)
      const alignTop = computeScrollTopToShowChildAtListTop({
        childOffsetTop: (lastAssistant as HTMLElement).offsetTop,
        scrollHeight: 1200,
        clientHeight: 200,
        marginPx: CHAT_ASSISTANT_MESSAGE_LIST_TOP_MARGIN_PX,
      })
      expect(assignedScrollTops).not.toContain(maxScroll)
      expect(assignedScrollTops).not.toContain(alignTop)
    })
  })
})
