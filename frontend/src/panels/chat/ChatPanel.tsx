import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { apiGet, apiPost } from '../../api'
import {
  parseChatResponse,
  type ChatLlmContextMeta,
  type ChatMessage,
  type VCenter,
} from '../../api/schemas'
import { asArray } from '../../utils/asArray'
import { ZonedRangeFields } from '../../datetime/ZonedRangeFields'
import { useTimeZone } from '../../datetime/useTimeZone'
import { resolveEventApiRange } from '../../datetime/graphRange'
import {
  METRICS_DEFAULT_ROLLING_DURATION_MS,
  presetRelativeRangeWallPartsWithUtcFallback,
  zonedRangePartsToCombinedInputs,
  type ZonedRangeParts,
} from '../../datetime/zonedRangeParts'
import { toErrorMessage } from '../../utils/errors'
import {
  CHAT_ASSISTANT_MESSAGE_LIST_TOP_MARGIN_PX,
  computeScrollTopToShowChildAtListTop,
} from './chatMessagesListScroll'
import { ChatMarkdownContent } from './ChatMarkdownContent'

/** メッセージリスト下端からの距離がこの値以下なら「最下部付近」とみなし、新着で追従する */
const CHAT_MESSAGES_STICKY_BOTTOM_THRESHOLD_PX = 48

/**
 * 期間集約コンテキスト付きの LLM チャットパネル。会話リストは最下部付近にいるときだけ追従し、
 * アシスタント応答後はそのメッセージ先頭が見える位置へ、ユーザーのみ末尾のときはリスト最下端へ寄せる。
 * 送信中はリスト末尾にプレースホルダ行を出し、`aria-busy` で状態を示す。
 */
export function ChatPanel({ onError }: { onError: (e: string | null) => void }) {
  const { timeZone } = useTimeZone()
  const [rangeParts, setRangeParts] = useState<ZonedRangeParts>(() =>
    presetRelativeRangeWallPartsWithUtcFallback(METRICS_DEFAULT_ROLLING_DURATION_MS, 'UTC'),
  )
  const [vcenterId, setVcenterId] = useState<string>('')
  const [vcenters, setVcenters] = useState<VCenter[]>([])
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(false)
  const [includePeriodMetricsCpu, setIncludePeriodMetricsCpu] = useState(false)
  const [includePeriodMetricsMemory, setIncludePeriodMetricsMemory] = useState(false)
  const [includePeriodMetricsDiskIo, setIncludePeriodMetricsDiskIo] = useState(false)
  const [includePeriodMetricsNetworkIo, setIncludePeriodMetricsNetworkIo] = useState(false)
  const [lastLlmContext, setLastLlmContext] = useState<ChatLlmContextMeta | null>(null)

  const messagesListRef = useRef<HTMLUListElement>(null)
  /** 最下部付近にいるときだけ `messages` 更新後に末尾へスクロールする */
  const stickToBottomRef = useRef(true)

  const syncStickToBottomFromScroll = useCallback(() => {
    const el = messagesListRef.current
    if (!el) return
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    stickToBottomRef.current = distanceFromBottom <= CHAT_MESSAGES_STICKY_BOTTOM_THRESHOLD_PX
  }, [])

  useLayoutEffect(() => {
    const list = messagesListRef.current
    if (!list || !stickToBottomRef.current) return

    if (loading) {
      list.scrollTop = Math.max(0, list.scrollHeight - list.clientHeight)
      return
    }

    const last = messages.at(-1)
    if (last?.role === 'assistant') {
      const item = list.querySelector('li.chat-panel__msg--assistant:last-of-type')
      if (item instanceof HTMLElement) {
        // `.chat-panel__messages` は `position: relative` により `li` の offsetTop がリスト内座標になる
        list.scrollTop = computeScrollTopToShowChildAtListTop({
          childOffsetTop: item.offsetTop,
          scrollHeight: list.scrollHeight,
          clientHeight: list.clientHeight,
          marginPx: CHAT_ASSISTANT_MESSAGE_LIST_TOP_MARGIN_PX,
        })
        return
      }
    }

    list.scrollTop = Math.max(0, list.scrollHeight - list.clientHeight)
  }, [messages, loading])

  useEffect(() => {
    void (async () => {
      try {
        const raw = await apiGet<unknown>('/api/vcenters')
        setVcenters(asArray<VCenter>(raw))
      } catch (e) {
        onError(toErrorMessage(e))
      }
    })()
  }, [onError])

  const send = useCallback(async () => {
    const text = draft.trim()
    if (!text) return

    const { rangeFromInput, rangeToInput } = zonedRangePartsToCombinedInputs(rangeParts)
    const resolved = resolveEventApiRange(rangeFromInput, rangeToInput, timeZone)
    if (!resolved.ok) {
      onError(resolved.message)
      return
    }
    if (!resolved.from || !resolved.to) {
      onError('期間の開始と終了を指定してください。')
      return
    }

    onError(null)
    const nextMessages: ChatMessage[] = [...messages, { role: 'user', content: text }]
    setMessages(nextMessages)
    setDraft('')
    setLoading(true)
    try {
      const body: Record<string, unknown> = {
        from: resolved.from,
        to: resolved.to,
        messages: nextMessages,
        include_period_metrics_cpu: includePeriodMetricsCpu,
        include_period_metrics_memory: includePeriodMetricsMemory,
        include_period_metrics_disk_io: includePeriodMetricsDiskIo,
        include_period_metrics_network_io: includePeriodMetricsNetworkIo,
      }
      if (vcenterId) {
        body.vcenter_id = vcenterId
      }
      const raw = await apiPost<unknown>('/api/chat', body)
      const out = parseChatResponse(raw)
      setLastLlmContext(out.llm_context ?? null)
      if (out.error) {
        setMessages((m) => [...m, { role: 'assistant', content: `（${out.error}）` }])
      } else {
        setMessages((m) => [...m, { role: 'assistant', content: out.assistant_content }])
      }
    } catch (e) {
      onError(toErrorMessage(e))
      setMessages((m) => m.slice(0, -1))
    } finally {
      setLoading(false)
    }
  }, [
    draft,
    messages,
    onError,
    rangeParts,
    timeZone,
    vcenterId,
    includePeriodMetricsCpu,
    includePeriodMetricsMemory,
    includePeriodMetricsDiskIo,
    includePeriodMetricsNetworkIo,
  ])

  const copyLatestAssistantReply = useCallback(async () => {
    let text = ''
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const m = messages[i]
      if (m.role === 'assistant') {
        text = m.content
        break
      }
    }
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }, [messages, onError])

  const canCopyLatestAssistantReply =
    messages.length > 0 && !loading && messages.at(-1)?.role === 'assistant'

  return (
    <div className="panel chat-panel">
      <p className="hint">
        指定期間のイベント・メトリクス集約を根拠に、質問・追質問ができます（会話はブラウザに保持し、サーバーは保存しません）。
      </p>

      <section className="chat-panel__section" aria-label="集計期間">
        <ZonedRangeFields value={rangeParts} onChange={setRangeParts} />
      </section>

      <section className="chat-panel__section" aria-label="vCenter">
        <label>
          対象 vCenter
          <select
            value={vcenterId}
            onChange={(e) => {
              setVcenterId(e.target.value)
            }}
          >
            <option value="">すべて（登録済み全体の集約）</option>
            {vcenters.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </label>
      </section>

      <section className="chat-panel__section" aria-label="期間メトリクス">
        <p className="hint chat-panel__metrics-hint">LLM に含めるメトリクス（期間内をバケット平均で送る・追加 DB クエリあり）</p>
        <label className="chat-panel__checkbox-label">
          <input
            type="checkbox"
            checked={includePeriodMetricsCpu}
            onChange={(e) => {
              setIncludePeriodMetricsCpu(e.target.checked)
            }}
            disabled={loading}
          />
          CPU 使用率
        </label>
        <label className="chat-panel__checkbox-label">
          <input
            type="checkbox"
            checked={includePeriodMetricsMemory}
            onChange={(e) => {
              setIncludePeriodMetricsMemory(e.target.checked)
            }}
            disabled={loading}
          />
          メモリ使用率
        </label>
        <label className="chat-panel__checkbox-label">
          <input
            type="checkbox"
            checked={includePeriodMetricsDiskIo}
            onChange={(e) => {
              setIncludePeriodMetricsDiskIo(e.target.checked)
            }}
            disabled={loading}
          />
          ディスク IO
        </label>
        <label className="chat-panel__checkbox-label">
          <input
            type="checkbox"
            checked={includePeriodMetricsNetworkIo}
            onChange={(e) => {
              setIncludePeriodMetricsNetworkIo(e.target.checked)
            }}
            disabled={loading}
          />
          ネットワーク IO
        </label>
      </section>

      <ul
        ref={messagesListRef}
        className="chat-panel__messages"
        aria-label="会話"
        aria-busy={loading ? 'true' : 'false'}
        onScroll={syncStickToBottomFromScroll}
      >
        {messages.map((m, i) => (
          <li key={`${i}-${m.role}`} className={`chat-panel__msg chat-panel__msg--${m.role}`}>
            <span className="chat-panel__role">{m.role === 'user' ? 'あなた' : 'アシスタント'}</span>
            <div className="chat-panel__bubble">
              <ChatMarkdownContent markdown={m.content} />
            </div>
            {i === messages.length - 1 && m.role === 'assistant' && (
              <div className="chat-panel__msg-actions">
                <button
                  type="button"
                  className="btn btn--gray"
                  disabled={!canCopyLatestAssistantReply}
                  onClick={() => void copyLatestAssistantReply()}
                >
                  最新の回答をコピー
                </button>
              </div>
            )}
          </li>
        ))}
        {loading && (
          <li className="chat-panel__msg chat-panel__msg--pending">
            <span className="chat-panel__role">アシスタント</span>
            <div className="chat-panel__bubble chat-panel__bubble--pending">応答を生成しています…</div>
          </li>
        )}
      </ul>

      {lastLlmContext != null && (
        <p className="hint chat-panel__llm-meta" role="status" aria-live="polite">
          LLM 入力（目安）: 推定 {lastLlmContext.estimated_input_tokens} / {lastLlmContext.max_input_tokens}{' '}
          トークン
          {lastLlmContext.json_truncated ? '・JSON 切り詰めあり' : '・JSON 切り詰めなし'}
          ・会話 {lastLlmContext.message_turns} ターン（トリム後）
        </p>
      )}

      <div className="chat-panel__composer-stack">
        <button
          type="button"
          className="btn btn--gray"
          disabled={loading || messages.length === 0}
          onClick={() => {
            if (!window.confirm('会話をすべて削除しますか？')) return
            setMessages([])
            setLastLlmContext(null)
          }}
        >
          会話をクリア
        </button>
        <div className="chat-panel__composer">
          <div className="chat-panel__composer-field">
            <label className="chat-panel__composer-label">
              メッセージ
              <textarea
                value={draft}
                onChange={(e) => {
                  setDraft(e.target.value)
                }}
                onKeyDown={(e) => {
                  // IME 確定中は Enter を横取りしない
                  if (e.nativeEvent.isComposing) return
                  if (e.key !== 'Enter') return
                  if (e.shiftKey) {
                    e.preventDefault()
                    setDraft((d) => `${d}\n`)
                    return
                  }
                  e.preventDefault()
                  void send()
                }}
                rows={3}
                disabled={loading}
                placeholder="質問を入力…"
              />
            </label>
          </div>
          <button type="button" className="btn" disabled={loading} onClick={() => void send()}>
            {loading ? '送信中…' : '送信'}
          </button>
        </div>
      </div>
    </div>
  )
}
