import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import '../../App.css'
import { TimeZoneProvider } from '../../datetime/TimeZoneProvider'
import { DISPLAY_TIME_ZONE_STORAGE_KEY } from '../../datetime/timeZoneStorage'
import { CHAT_MAX_STORED_MESSAGES_STORAGE_KEY } from '../../preferences/chatMaxStoredMessagesStorage'
import { ChatMaxStoredMessagesProvider } from '../../preferences/ChatMaxStoredMessagesProvider'
import { ChatSamplePromptsProvider } from '../../preferences/ChatSamplePromptsProvider'
import { CHAT_PANEL_STORAGE_KEY, writeChatPanelSnapshot } from '../../preferences/chatPanelStorage'
import {
  CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY,
  CHAT_SAMPLE_PROMPTS_STORAGE_KEY,
} from '../../preferences/chatSamplePromptsStorage'
import {
  CHAT_ASSISTANT_MESSAGE_LIST_TOP_MARGIN_PX,
  computeScrollTopToShowChildAtListTop,
} from './chatMessagesListScroll'
import { ChatPanel } from './ChatPanel'

const CHAT_PANEL_TEST_TIMEOUT_MS = 20_000

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderChat(onError: (e: string | null) => void = vi.fn()) {
  return render(
    <TimeZoneProvider>
      <ChatMaxStoredMessagesProvider>
        <ChatSamplePromptsProvider>
          <ChatPanel onError={onError} />
        </ChatSamplePromptsProvider>
      </ChatMaxStoredMessagesProvider>
    </TimeZoneProvider>,
  )
}

function messagesListElement(): HTMLElement {
  const el = document.querySelector('ul.chat-panel__messages')
  if (!el) throw new Error('ul.chat-panel__messages が見つかりません')
  return el as HTMLElement
}

function readPeriodContextPayloadFields(body: Record<string, unknown>) {
  return {
    from: body.from,
    to: body.to,
    vcenter_id: body.vcenter_id,
    include_period_metrics_cpu: body.include_period_metrics_cpu,
    include_period_metrics_memory: body.include_period_metrics_memory,
    include_period_metrics_disk_io: body.include_period_metrics_disk_io,
    include_period_metrics_network_io: body.include_period_metrics_network_io,
    metric_threshold_cpu_pct: body.metric_threshold_cpu_pct,
    metric_threshold_memory_pct: body.metric_threshold_memory_pct,
    metric_threshold_disk_pct: body.metric_threshold_disk_pct,
    metric_threshold_network_pct: body.metric_threshold_network_pct,
  }
}

/** チャットコンポーザー周りのスタイルが意図どおりか（happy-dom の getComputedStyle が弱いためソースを検査する） */
function readChatPanelCss(): string {
  const dir = path.dirname(fileURLToPath(import.meta.url))
  return readFileSync(path.join(dir, './ChatPanel.css'), 'utf8')
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

describe(
  'ChatPanel',
  {
    timeout: CHAT_PANEL_TEST_TIMEOUT_MS,
  },
  () => {
  beforeEach(() => {
    localStorage.removeItem(CHAT_PANEL_STORAGE_KEY)
    localStorage.removeItem(CHAT_MAX_STORED_MESSAGES_STORAGE_KEY)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.removeItem(DISPLAY_TIME_ZONE_STORAGE_KEY)
    localStorage.removeItem(CHAT_SAMPLE_PROMPTS_STORAGE_KEY)
    localStorage.removeItem(CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY)
    localStorage.removeItem(CHAT_PANEL_STORAGE_KEY)
    localStorage.removeItem(CHAT_MAX_STORED_MESSAGES_STORAGE_KEY)
  })

  it(
    '送信で POST /api/chat が呼ばれ、アシスタントの返答が表示される',
    async () => {
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
  },
    15_000,
  )

  it(
    'アシスタント応答の GFM テーブルを描画する',
    async () => {
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

      await waitFor(
        () => {
          expect(screen.getByRole('table')).toBeInTheDocument()
        },
        { timeout: 12_000 },
      )
      expect(screen.getByRole('columnheader', { name: '列A' })).toBeInTheDocument()
      expect(screen.getByRole('cell', { name: '2' })).toBeInTheDocument()
    },
    15_000,
  )

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
    expect(kids.length).toBe(3)
    expect(kids[0].className).toMatch(/chat-panel__composer-field/)
    expect(kids[1]).toBeInstanceOf(HTMLButtonElement)
    expect((kids[1] as HTMLButtonElement).getAttribute('aria-label')).toBe('プレビュー')
    expect(kids[2]).toBeInstanceOf(HTMLButtonElement)
    expect((kids[2] as HTMLButtonElement).getAttribute('aria-label')).toBe('送信')
  })

  it('ChatPanel.css でコンポーザーが横並び（flex-direction: row）になる', () => {
    const css = readChatPanelCss()
    expect(css).toMatch(/\.chat-panel__composer\s*\{[^}]*flex-direction:\s*row/s)
  })

  it('ChatPanel.css の狭い画面メディアクエリ内でコンポーザーが縦積みになる', () => {
    const css = readChatPanelCss()
    const mediaStart = css.indexOf('@media (max-width: 768px)')
    expect(mediaStart).toBeGreaterThanOrEqual(0)
    expect(css.slice(mediaStart)).toMatch(/\.chat-panel__composer[\s\S]*?flex-direction:\s*column/)
  })

  it('ChatPanel.css でコンポーザー内 textarea の上限幅が 560px より広い', () => {
    const css = readChatPanelCss()
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

  it('サンプルをクリックするたび下書きへ即時追記され、クリック順が反映される', async () => {
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

    const ta = screen.getByPlaceholderText('質問を入力…') as HTMLTextAreaElement
    expect(ta.value).toContain('## メトリクス観測')
    expect(ta.value).toContain('## 上位イベント（重要度順）')
    expect(ta.value.indexOf('## メトリクス観測')).toBeLessThan(
      ta.value.indexOf('## 上位イベント（重要度順）'),
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

    const ta = screen.getByPlaceholderText('質問を入力…') as HTMLTextAreaElement
    expect(ta.value.startsWith('既存')).toBe(true)
    expect(ta.value).toContain('## 上位イベント（重要度順）')
  })

  it('送信中はサンプルチップが無効になる', async () => {
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

  it(
    'アシスタントが2件のときそれぞれの回答をコピーできる',
    async () => {
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
      expect(postCount).toBe(1)
    })

    fireEvent.change(ta, { target: { value: '二問目' } })
    fireEvent.click(screen.getByRole('button', { name: '送信' }))
    await waitFor(() => {
      expect(postCount).toBe(2)
    })

    const conversation = screen.getByRole('list', { name: '会話' })
    let copyButtons: HTMLButtonElement[] = []
    await waitFor(() => {
      copyButtons = within(conversation).getAllByRole('button', { name: '回答をコピー' }) as HTMLButtonElement[]
      expect(copyButtons.length).toBe(2)
    })

    fireEvent.click(copyButtons[0] as HTMLButtonElement)
    await waitFor(() => {
      expect(writeText).toHaveBeenLastCalledWith('回答A')
    })

    fireEvent.click(copyButtons[1] as HTMLButtonElement)
    await waitFor(() => {
      expect(writeText).toHaveBeenLastCalledWith('回答B')
    })
  },
    15_000,
  )

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

  it('送信時にメトリクス有効化フラグと閾値4項目が POST 本文に含まれる', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      if (url.endsWith('/api/chat') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as {
          include_period_metrics_cpu?: boolean
          metric_threshold_cpu_pct?: number
          metric_threshold_memory_pct?: number
          metric_threshold_disk_pct?: number
          metric_threshold_network_pct?: number
        }
        expect(body.include_period_metrics_cpu).toBe(true)
        expect(body.metric_threshold_cpu_pct).toBe(80)
        expect(body.metric_threshold_memory_pct).toBe(85)
        expect(body.metric_threshold_disk_pct).toBe(75)
        expect(body.metric_threshold_network_pct).toBe(75)
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

  it('プレビュー時に変更した閾値4項目を POST /api/chat/preview 本文へ送る', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      if (url.endsWith('/api/chat/preview') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as {
          metric_threshold_cpu_pct?: number
          metric_threshold_memory_pct?: number
          metric_threshold_disk_pct?: number
          metric_threshold_network_pct?: number
        }
        expect(body.metric_threshold_cpu_pct).toBe(81)
        expect(body.metric_threshold_memory_pct).toBe(82)
        expect(body.metric_threshold_disk_pct).toBe(73)
        expect(body.metric_threshold_network_pct).toBe(74)
        return Promise.resolve(
          jsonResponse({
            context_block: 'ctx',
            conversation: [{ role: 'user', content: '質問' }],
          }),
        )
      }
      return Promise.resolve(new Response('not found', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderChat()
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })

    fireEvent.change(screen.getByRole('spinbutton', { name: 'CPU 閾値（%）' }), {
      target: { value: '81' },
    })
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Memory 閾値（%）' }), {
      target: { value: '82' },
    })
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Disk 閾値（%）' }), {
      target: { value: '73' },
    })
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Network 閾値（%）' }), {
      target: { value: '74' },
    })
    fireEvent.change(screen.getByPlaceholderText('質問を入力…'), {
      target: { value: '質問' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'プレビュー' }))

    await waitFor(() => {
      const posts = fetchMock.mock.calls.filter(
        (c) => String(c[0]).endsWith('/api/chat/preview') && (c[1] as RequestInit)?.method === 'POST',
      )
      expect(posts.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('送信とプレビューで期間コンテキスト本文のフィールド構成が一致する', async () => {
    let chatPayload: Record<string, unknown> | null = null
    let previewPayload: Record<string, unknown> | null = null

    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(
          jsonResponse([{ id: 'vc-1', name: 'vCenter 1' }]),
        )
      }
      if (url.endsWith('/api/chat/preview') && init?.method === 'POST') {
        previewPayload = JSON.parse(String(init.body)) as Record<string, unknown>
        return Promise.resolve(
          jsonResponse({
            context_block: 'ctx',
            conversation: [{ role: 'user', content: '質問' }],
          }),
        )
      }
      if (url.endsWith('/api/chat') && init?.method === 'POST') {
        chatPayload = JSON.parse(String(init.body)) as Record<string, unknown>
        return Promise.resolve(jsonResponse({ assistant_content: 'ok', error: null }))
      }
      return Promise.resolve(new Response('not found', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderChat()
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })

    fireEvent.change(screen.getByLabelText('対象 vCenter'), { target: { value: 'vc-1' } })
    fireEvent.click(screen.getByRole('checkbox', { name: /^CPU 使用率$/ }))
    fireEvent.click(screen.getByRole('checkbox', { name: /^ネットワーク IO$/ }))
    fireEvent.change(screen.getByRole('spinbutton', { name: 'CPU 閾値（%）' }), {
      target: { value: '91' },
    })
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Memory 閾値（%）' }), {
      target: { value: '77' },
    })
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Disk 閾値（%）' }), {
      target: { value: '66' },
    })
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Network 閾値（%）' }), {
      target: { value: '55' },
    })

    fireEvent.change(screen.getByPlaceholderText('質問を入力…'), {
      target: { value: '質問' },
    })
    fireEvent.click(screen.getByRole('button', { name: '送信' }))
    await waitFor(() => {
      expect(chatPayload).not.toBeNull()
    })

    fireEvent.change(screen.getByPlaceholderText('質問を入力…'), {
      target: { value: '質問' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'プレビュー' }))
    await waitFor(() => {
      expect(previewPayload).not.toBeNull()
    })

    expect(chatPayload).not.toBeNull()
    expect(previewPayload).not.toBeNull()
    if (!chatPayload || !previewPayload) {
      throw new Error('送信またはプレビューの本文が取得できませんでした')
    }
    expect(readPeriodContextPayloadFields(chatPayload)).toEqual(
      readPeriodContextPayloadFields(previewPayload),
    )
  })

  it('閾値の空入力や範囲外入力は API 本文へ反映しない', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      if (url.endsWith('/api/chat') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as {
          metric_threshold_cpu_pct?: number
          metric_threshold_memory_pct?: number
          metric_threshold_disk_pct?: number
          metric_threshold_network_pct?: number
        }
        expect(body.metric_threshold_cpu_pct).toBe(80)
        expect(body.metric_threshold_memory_pct).toBe(85)
        expect(body.metric_threshold_disk_pct).toBe(75)
        expect(body.metric_threshold_network_pct).toBe(75)
        return Promise.resolve(jsonResponse({ assistant_content: 'ok', error: null }))
      }
      return Promise.resolve(new Response('not found', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderChat()
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })

    const cpu = screen.getByRole('spinbutton', { name: 'CPU 閾値（%）' })
    const memory = screen.getByRole('spinbutton', { name: 'Memory 閾値（%）' })
    const disk = screen.getByRole('spinbutton', { name: 'Disk 閾値（%）' })
    const network = screen.getByRole('spinbutton', { name: 'Network 閾値（%）' })

    fireEvent.change(cpu, { target: { value: '' } })
    fireEvent.change(memory, { target: { value: '101' } })
    fireEvent.change(disk, { target: { value: '-1' } })
    fireEvent.change(network, { target: { value: '-' } })

    fireEvent.blur(cpu)
    fireEvent.blur(memory)
    fireEvent.blur(disk)
    fireEvent.blur(network)

    fireEvent.change(screen.getByPlaceholderText('質問を入力…'), {
      target: { value: '閾値ガード確認' },
    })
    fireEvent.click(screen.getByRole('button', { name: '送信' }))

    await waitFor(() => {
      expect(screen.getByText('ok')).toBeInTheDocument()
    })
  })

  describe('localStorage 永続化', () => {
    it('送信後にチャットパネル状態が localStorage に保存される', async () => {
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.endsWith('/api/vcenters')) {
          return Promise.resolve(jsonResponse([]))
        }
        if (url.endsWith('/api/chat') && init?.method === 'POST') {
          return Promise.resolve(
            jsonResponse({ assistant_content: '永続テスト回答', error: null }),
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
        target: { value: '永続テスト質問' },
      })
      fireEvent.click(screen.getByRole('button', { name: '送信' }))

      await waitFor(() => {
        expect(screen.getByText('永続テスト回答')).toBeInTheDocument()
      })

      await waitFor(() => {
        const raw = localStorage.getItem(CHAT_PANEL_STORAGE_KEY)
        expect(raw).toBeTruthy()
        const snap = JSON.parse(String(raw)) as { messages: { role: string; content: string }[] }
        const lastTwo = snap.messages.slice(-2)
        expect(lastTwo.length).toBe(2)
        expect(lastTwo[0]?.role).toBe('user')
        expect(lastTwo[0]?.content).toBe('永続テスト質問')
        expect(lastTwo[1]?.content).toContain('永続テスト回答')
      })
    })

    it('マウント時に保存済み会話を復元する', async () => {
      writeChatPanelSnapshot(
        {
          messages: [
            { role: 'user', content: '保存済み質問' },
            { role: 'assistant', content: '保存済み回答' },
          ],
          rangeParts: {
            fromDate: '2026-01-01',
            fromTime: '00:00',
            toDate: '2026-01-02',
            toTime: '23:59',
          },
          vcenterId: '',
          includePeriodMetricsCpu: false,
          includePeriodMetricsMemory: false,
          includePeriodMetricsDiskIo: false,
          includePeriodMetricsNetworkIo: false,
          draft: '',
        },
        200,
      )

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
        expect(screen.getByText('保存済み回答')).toBeInTheDocument()
      })
      expect(screen.getByText('保存済み質問')).toBeInTheDocument()
    })

    it('会話をクリアでストレージキーが削除される', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
      writeChatPanelSnapshot(
        {
          messages: [{ role: 'user', content: 'x' }],
          rangeParts: {
            fromDate: '2026-01-01',
            fromTime: '00:00',
            toDate: '2026-01-02',
            toTime: '23:59',
          },
          vcenterId: '',
          includePeriodMetricsCpu: false,
          includePeriodMetricsMemory: false,
          includePeriodMetricsDiskIo: false,
          includePeriodMetricsNetworkIo: false,
          draft: '',
        },
        200,
      )

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
        expect(screen.getByText('x')).toBeInTheDocument()
      })

      fireEvent.click(screen.getByRole('button', { name: '会話をクリア' }))

      await waitFor(() => {
        expect(localStorage.getItem(CHAT_PANEL_STORAGE_KEY)).toBeNull()
      })
      confirmSpy.mockRestore()
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

  it('プレビュー取得後もインシデント統合タイムラインをインライン表示しない', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      if (url.endsWith('/api/chat/preview') && init?.method === 'POST') {
        return Promise.resolve(
          jsonResponse({
            context_block: 'ctx',
            conversation: [{ role: 'user', content: '質問' }],
            incident_timeline: {
              columns: [
                {
                  timestamp_utc: '2026-05-07T00:00:00Z',
                  items: [
                    { timestamp_utc: '2026-05-07T00:00:00Z', kind: 'event', title: 'イベント' },
                    { timestamp_utc: '2026-05-07T00:00:00Z', kind: 'alert', title: 'アラート' },
                  ],
                  visible_items: [{ timestamp_utc: '2026-05-07T00:00:00Z', kind: 'alert', title: 'アラート' }],
                  hidden_count: 1,
                },
              ],
            },
          }),
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
      target: { value: '質問' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'プレビュー' }))

    await waitFor(() => {
      expect(screen.getByText('プロンプトプレビュー')).toBeInTheDocument()
    })
    expect(screen.queryByText('インシデント統合タイムライン')).not.toBeInTheDocument()
    expect(screen.queryByText('アラート')).not.toBeInTheDocument()
  })

  it('モーダルを閉じるとプレビューだけ閉じ、タイムラインは引き続きインライン表示されない', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      if (url.endsWith('/api/chat/preview') && init?.method === 'POST') {
        return Promise.resolve(
          jsonResponse({
            context_block: 'ctx',
            conversation: [{ role: 'user', content: '質問' }],
            incident_timeline: {
              columns: [
                {
                  timestamp_utc: '2026-05-07T00:00:00Z',
                  items: [{ timestamp_utc: '2026-05-07T00:00:00Z', kind: 'alert', title: '重大アラート' }],
                  visible_items: [{ timestamp_utc: '2026-05-07T00:00:00Z', kind: 'alert', title: '重大アラート' }],
                  hidden_count: 0,
                },
              ],
            },
          }),
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
      target: { value: '質問' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'プレビュー' }))

    await waitFor(() => {
      expect(screen.getByText('プロンプトプレビュー')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByLabelText('閉じる'))

    await waitFor(() => {
      expect(screen.queryByText('プロンプトプレビュー')).not.toBeInTheDocument()
    })
    expect(screen.queryByText('インシデント統合タイムライン')).not.toBeInTheDocument()
    expect(screen.queryByText('重大アラート')).not.toBeInTheDocument()
  })
  },
)
