import { useCallback, useLayoutEffect, useRef } from 'react'
import type { ChatMessage } from '../../api/schemas'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import {
  CHAT_ASSISTANT_MESSAGE_LIST_TOP_MARGIN_PX,
  computeScrollTopToShowChildAtListTop,
} from './chatMessagesListScroll'
import { ChatCopyAnswerSvg } from './chatPanelIcons'
import { ChatMarkdownContent } from './ChatMarkdownContent'

/** メッセージリスト下端からの距離がこの値以下なら「最下部付近」とみなし、新着で追従する */
const CHAT_MESSAGES_STICKY_BOTTOM_THRESHOLD_PX = 48

type ChatMessagesListProps = {
  messages: ChatMessage[]
  loading: boolean
  timeZone: string
  onCopyAssistantMessage: (content: string) => void | Promise<void>
  /** 送信中プレースホルダの文言（未指定時は既定文言） */
  pendingLabel?: string
}

/** チャット会話メッセージ一覧。 */
export function ChatMessagesList({
  messages,
  loading,
  timeZone,
  onCopyAssistantMessage,
  pendingLabel,
}: ChatMessagesListProps) {
  const messagesListRef = useRef<HTMLUListElement>(null)
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

  return (
    <ul
      ref={messagesListRef}
      className="chat-panel__messages"
      aria-label="会話"
      aria-busy={loading ? 'true' : 'false'}
      onScroll={syncStickToBottomFromScroll}
    >
      {messages.map((m, i) => (
        <li key={`${i}-${m.role}`} className={`chat-panel__msg chat-panel__msg--${m.role}`}>
          <span className="chat-panel__role">
            {m.role === 'user' ? 'あなた' : 'アシスタント'}
            {m.created_at && (
              <span className="chat-panel__msg-meta">
                {' '}- {formatIsoInTimeZone(m.created_at, timeZone)}
                {m.latency_ms != null && (
                  <span className="chat-panel__metrics">
                    {' '}
                    （
                    {m.token_per_sec != null ? `${m.token_per_sec.toFixed(1)} tokens/sec | ` : ''}
                    latency {(m.latency_ms / 1000).toFixed(1)}s）
                  </span>
                )}
              </span>
            )}
          </span>
          <div className="chat-panel__bubble">
            <ChatMarkdownContent markdown={m.content} />
          </div>
          {m.role === 'assistant' && (
            <div className="chat-panel__msg-actions">
              <button
                type="button"
                className="btn btn--gray chat-panel__icon-btn chat-panel__copy-answer-btn"
                aria-label="回答をコピー"
                title="回答をコピー"
                disabled={!m.content.trim()}
                onClick={() => void onCopyAssistantMessage(m.content)}
              >
                <ChatCopyAnswerSvg />
              </button>
            </div>
          )}
        </li>
      ))}
      {loading && (
        <li className="chat-panel__msg chat-panel__msg--pending">
          <span className="chat-panel__role">アシスタント</span>
          <div className="chat-panel__bubble chat-panel__bubble--pending">
            {pendingLabel ?? '応答を生成しています…'}
          </div>
        </li>
      )}
    </ul>
  )
}
