import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import './ChatPanel.css'

import { apiGet, apiPost } from '../../api'
import { buildIncidentTimelineBuildRequestPayload } from '../../api/buildIncidentTimelineBuildRequestPayload'
import { readStoredChatMaxStoredMessages } from '../../preferences/chatMaxStoredMessagesStorage'
import { useChatMaxStoredMessages } from '../../preferences/useChatMaxStoredMessages'
import { useChatSamplePrompts } from '../../preferences/useChatSamplePrompts'
import {
  parseChatResponse,
  parseChatPreviewResponse,
  type ChatLlmContextMeta,
  type ChatMessage,
  type ChatPreviewResponse,
  type VCenter,
} from '../../api/schemas'
import { asArray } from '../../utils/asArray'
import { ZonedRangeFields } from '../../datetime/ZonedRangeFields'
import { useTimeZone } from '../../datetime/useTimeZone'
import { resolveEventApiRange } from '../../datetime/graphRange'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
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
import {
  CHAT_LLM_CONTEXT_MAX_MESSAGES,
  clearChatPanelSnapshot,
  readChatPanelSnapshot,
  trimChatMessagesToMax,
  writeChatPanelSnapshot,
} from '../../preferences/chatPanelStorage'
import { appendChatSampleTextToDraft } from './appendChatSampleTextToDraft'
import { ChatCopyAnswerSvg, ChatPreviewSvg, ChatSendSvg } from './chatPanelIcons'
import { ChatMarkdownContent } from './ChatMarkdownContent'
import { ChatPromptPreviewModal } from './ChatPromptPreviewModal'

/** メッセージリスト下端からの距離がこの値以下なら「最下部付近」とみなし、新着で追従する */
const CHAT_MESSAGES_STICKY_BOTTOM_THRESHOLD_PX = 48

/** 下書きを localStorage に反映するまでの待機（入力のたびに書き込まない） */
const CHAT_DRAFT_PERSIST_DEBOUNCE_MS = 400
const DEFAULT_METRIC_THRESHOLD_CPU_PCT = 80
const DEFAULT_METRIC_THRESHOLD_MEMORY_PCT = 85
const DEFAULT_METRIC_THRESHOLD_DISK_PCT = 75
const DEFAULT_METRIC_THRESHOLD_NETWORK_PCT = 75

function isValidMetricThresholdPercent(value: number): boolean {
  return Number.isFinite(value) && value >= 0 && value <= 100
}

/**
 * 期間集約コンテキスト付きの LLM チャットパネル。会話リストは最下部付近にいるときだけ追従し、
 * アシスタント応答後はそのメッセージ先頭が見える位置へ、ユーザーのみ末尾のときはリスト最下端へ寄せる。
 * 送信中はリスト末尾にプレースホルダ行を出し、`aria-busy` で状態を示す。
 * サンプル質問はチップをクリックすると textarea 末尾へ即時追記する（送信はしない。`ChatSamplePromptsProvider` 必須）。
 */
export function ChatPanel({ onError }: { onError: (e: string | null) => void }) {
  const { timeZone } = useTimeZone()
  const { chatMaxStoredMessages } = useChatMaxStoredMessages()
  const { visibleChatSamplePrompts } = useChatSamplePrompts()
  const [rangeParts, setRangeParts] = useState<ZonedRangeParts>(() =>
    presetRelativeRangeWallPartsWithUtcFallback(METRICS_DEFAULT_ROLLING_DURATION_MS, 'UTC'),
  )
  const [vcenterId, setVcenterId] = useState<string>('')
  const [vcenters, setVcenters] = useState<VCenter[]>([])
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [previewData, setPreviewData] = useState<ChatPreviewResponse | null>(null)
  const [isPreviewModalOpen, setIsPreviewModalOpen] = useState(false)
  const [includePeriodMetricsCpu, setIncludePeriodMetricsCpu] = useState(false)
  const [includePeriodMetricsMemory, setIncludePeriodMetricsMemory] = useState(false)
  const [includePeriodMetricsDiskIo, setIncludePeriodMetricsDiskIo] = useState(false)
  const [includePeriodMetricsNetworkIo, setIncludePeriodMetricsNetworkIo] = useState(false)
  const [metricThresholdCpuPct, setMetricThresholdCpuPct] = useState(DEFAULT_METRIC_THRESHOLD_CPU_PCT)
  const [metricThresholdCpuInput, setMetricThresholdCpuInput] = useState(
    String(DEFAULT_METRIC_THRESHOLD_CPU_PCT),
  )
  const [metricThresholdMemoryPct, setMetricThresholdMemoryPct] = useState(
    DEFAULT_METRIC_THRESHOLD_MEMORY_PCT,
  )
  const [metricThresholdMemoryInput, setMetricThresholdMemoryInput] = useState(
    String(DEFAULT_METRIC_THRESHOLD_MEMORY_PCT),
  )
  const [metricThresholdDiskPct, setMetricThresholdDiskPct] = useState(DEFAULT_METRIC_THRESHOLD_DISK_PCT)
  const [metricThresholdDiskInput, setMetricThresholdDiskInput] = useState(
    String(DEFAULT_METRIC_THRESHOLD_DISK_PCT),
  )
  const [metricThresholdNetworkPct, setMetricThresholdNetworkPct] = useState(
    DEFAULT_METRIC_THRESHOLD_NETWORK_PCT,
  )
  const [metricThresholdNetworkInput, setMetricThresholdNetworkInput] = useState(
    String(DEFAULT_METRIC_THRESHOLD_NETWORK_PCT),
  )
  const [lastLlmContext, setLastLlmContext] = useState<ChatLlmContextMeta | null>(null)
  /** `localStorage` からの初回復元が終わるまで永続化 `write` しない */
  const [storageHydrated, setStorageHydrated] = useState(false)
  /** `draft` の debounce 反映値（永続化スナップショットの `draft` に使う） */
  const [debouncedDraft, setDebouncedDraft] = useState('')
  /** 「会話をクリア」直後のみ、空状態での `write` をスキップしてキー削除を維持する */
  const skipNextPersistRef = useRef(false)
  /** `localStorage` 書き込み失敗を連続で `onError` しないためのフラグ（成功時にリセット） */
  const storageWriteErrorReportedRef = useRef(false)
  /** 初回マウントでは `chatMaxStoredMessages` 変更によるトリムをスキップ（ハイドレートと競合させない） */
  const skipMaxTrimOnMountRef = useRef(true)

  const messagesListRef = useRef<HTMLUListElement>(null)
  const draftTextareaRef = useRef<HTMLTextAreaElement>(null)
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

  useEffect(() => {
    const id = window.setTimeout(() => {
      setDebouncedDraft(draft)
    }, CHAT_DRAFT_PERSIST_DEBOUNCE_MS)
    return () => window.clearTimeout(id)
  }, [draft])

  useEffect(() => {
    const max = readStoredChatMaxStoredMessages()
    const snap = readChatPanelSnapshot(max)
    if (snap) {
      setRangeParts(snap.rangeParts)
      setVcenterId(snap.vcenterId)
      setMessages(snap.messages)
      setDraft(snap.draft)
      setDebouncedDraft(snap.draft)
      setIncludePeriodMetricsCpu(snap.includePeriodMetricsCpu)
      setIncludePeriodMetricsMemory(snap.includePeriodMetricsMemory)
      setIncludePeriodMetricsDiskIo(snap.includePeriodMetricsDiskIo)
      setIncludePeriodMetricsNetworkIo(snap.includePeriodMetricsNetworkIo)
    }
    setStorageHydrated(true)
  }, [])

  useEffect(() => {
    if (skipMaxTrimOnMountRef.current) {
      skipMaxTrimOnMountRef.current = false
      return
    }
    setMessages((m) => trimChatMessagesToMax(m, chatMaxStoredMessages))
  }, [chatMaxStoredMessages])

  useEffect(() => {
    if (!storageHydrated) {
      return
    }
    if (skipNextPersistRef.current) {
      skipNextPersistRef.current = false
      return
    }
    const ok = writeChatPanelSnapshot(
      {
        messages,
        rangeParts,
        vcenterId,
        includePeriodMetricsCpu,
        includePeriodMetricsMemory,
        includePeriodMetricsDiskIo,
        includePeriodMetricsNetworkIo,
        draft: debouncedDraft,
      },
      chatMaxStoredMessages,
    )
    if (ok) {
      storageWriteErrorReportedRef.current = false
    } else if (!storageWriteErrorReportedRef.current) {
      storageWriteErrorReportedRef.current = true
      onError('ブラウザの保存領域が不足しているため、会話の保存に失敗しました。')
    }
  }, [
    storageHydrated,
    messages,
    rangeParts,
    vcenterId,
    includePeriodMetricsCpu,
    includePeriodMetricsMemory,
    includePeriodMetricsDiskIo,
    includePeriodMetricsNetworkIo,
    debouncedDraft,
    onError,
    chatMaxStoredMessages,
  ])

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
    const nextMessages = trimChatMessagesToMax(
      [...messages, { role: 'user', content: text, created_at: new Date().toISOString() }],
      chatMaxStoredMessages,
    )
    setMessages(nextMessages)
    setDraft('')
    setDebouncedDraft('')
    setLoading(true)
    try {
      const body: Record<string, unknown> = {
        ...buildIncidentTimelineBuildRequestPayload({
          resolvedRange: { from: resolved.from, to: resolved.to },
          options: {
            vcenterId,
            includePeriodMetricsCpu,
            includePeriodMetricsMemory,
            includePeriodMetricsDiskIo,
            includePeriodMetricsNetworkIo,
            metricThresholdCpuPct,
            metricThresholdMemoryPct,
            metricThresholdDiskPct,
            metricThresholdNetworkPct,
          },
        }),
        messages: trimChatMessagesToMax(nextMessages, CHAT_LLM_CONTEXT_MAX_MESSAGES),
      }
      const raw = await apiPost<unknown>('/api/chat', body)
      const out = parseChatResponse(raw)
      setLastLlmContext(out.llm_context ?? null)
      if (out.error) {
        setMessages((m) =>
          trimChatMessagesToMax(
            [
              ...m,
              {
                role: 'assistant',
                content: `（${out.error}）`,
                created_at: out.created_at,
                latency_ms: out.latency_ms ?? undefined,
                token_per_sec: out.token_per_sec ?? undefined,
              },
            ],
            chatMaxStoredMessages,
          ),
        )
      } else {
        setMessages((m) =>
          trimChatMessagesToMax(
            [
              ...m,
              {
                role: 'assistant',
                content: out.assistant_content,
                created_at: out.created_at,
                latency_ms: out.latency_ms ?? undefined,
                token_per_sec: out.token_per_sec ?? undefined,
              },
            ],
            chatMaxStoredMessages,
          ),
        )
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
    metricThresholdCpuPct,
    metricThresholdMemoryPct,
    metricThresholdDiskPct,
    metricThresholdNetworkPct,
    chatMaxStoredMessages,
  ])

  const previewPrompt = useCallback(async () => {
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
    const nextMessages = trimChatMessagesToMax(
      [...messages, { role: 'user', content: text }],
      chatMaxStoredMessages,
    )
    
    setPreviewing(true)
    try {
      const body: Record<string, unknown> = {
        ...buildIncidentTimelineBuildRequestPayload({
          resolvedRange: { from: resolved.from, to: resolved.to },
          options: {
            vcenterId,
            includePeriodMetricsCpu,
            includePeriodMetricsMemory,
            includePeriodMetricsDiskIo,
            includePeriodMetricsNetworkIo,
            metricThresholdCpuPct,
            metricThresholdMemoryPct,
            metricThresholdDiskPct,
            metricThresholdNetworkPct,
          },
        }),
        messages: trimChatMessagesToMax(nextMessages, CHAT_LLM_CONTEXT_MAX_MESSAGES),
      }
      const raw = await apiPost<unknown>('/api/chat/preview', body)
      const out = parseChatPreviewResponse(raw)
      setPreviewData(out)
      setIsPreviewModalOpen(true)
    } catch (e) {
      onError(toErrorMessage(e))
    } finally {
      setPreviewing(false)
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
    metricThresholdCpuPct,
    metricThresholdMemoryPct,
    metricThresholdDiskPct,
    metricThresholdNetworkPct,
    chatMaxStoredMessages,
  ])

  const copyAssistantMessageContent = useCallback(
    async (content: string) => {
      const text = content.trim()
      if (!text) return
      try {
        await navigator.clipboard.writeText(text)
      } catch (e) {
        onError(toErrorMessage(e))
      }
    },
    [onError],
  )

  const handleMetricThresholdInputChange = useCallback(
    (
      rawValue: string,
      setInput: (value: string) => void,
      setValue: (value: number) => void,
    ) => {
      setInput(rawValue)
      if (rawValue.trim() === '') {
        return
      }
      const parsed = Number(rawValue)
      if (!isValidMetricThresholdPercent(parsed)) {
        return
      }
      setValue(parsed)
    },
    [],
  )

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

      <section className="chat-panel__section" aria-label="メトリクス閾値">
        <p className="hint chat-panel__metrics-hint">インシデント判定に使う閾値（%）</p>
        <div className="chat-panel__threshold-grid">
          <label className="chat-panel__threshold-field">
            CPU 閾値（%）
            <input
              type="number"
              min={0}
              max={100}
              step={1}
              value={metricThresholdCpuInput}
              onChange={(e) =>
                handleMetricThresholdInputChange(
                  e.target.value,
                  setMetricThresholdCpuInput,
                  setMetricThresholdCpuPct,
                )
              }
              onBlur={() => setMetricThresholdCpuInput(String(metricThresholdCpuPct))}
              disabled={loading}
            />
          </label>
          <label className="chat-panel__threshold-field">
            Memory 閾値（%）
            <input
              type="number"
              min={0}
              max={100}
              step={1}
              value={metricThresholdMemoryInput}
              onChange={(e) =>
                handleMetricThresholdInputChange(
                  e.target.value,
                  setMetricThresholdMemoryInput,
                  setMetricThresholdMemoryPct,
                )
              }
              onBlur={() => setMetricThresholdMemoryInput(String(metricThresholdMemoryPct))}
              disabled={loading}
            />
          </label>
          <label className="chat-panel__threshold-field">
            Disk 閾値（%）
            <input
              type="number"
              min={0}
              max={100}
              step={1}
              value={metricThresholdDiskInput}
              onChange={(e) =>
                handleMetricThresholdInputChange(
                  e.target.value,
                  setMetricThresholdDiskInput,
                  setMetricThresholdDiskPct,
                )
              }
              onBlur={() => setMetricThresholdDiskInput(String(metricThresholdDiskPct))}
              disabled={loading}
            />
          </label>
          <label className="chat-panel__threshold-field">
            Network 閾値（%）
            <input
              type="number"
              min={0}
              max={100}
              step={1}
              value={metricThresholdNetworkInput}
              onChange={(e) =>
                handleMetricThresholdInputChange(
                  e.target.value,
                  setMetricThresholdNetworkInput,
                  setMetricThresholdNetworkPct,
                )
              }
              onBlur={() => setMetricThresholdNetworkInput(String(metricThresholdNetworkPct))}
              disabled={loading}
            />
          </label>
        </div>
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
            <span className="chat-panel__role">
              {m.role === 'user' ? 'あなた' : 'アシスタント'}
              {m.created_at && (
                <span className="chat-panel__msg-meta">
                  {' '}- {formatIsoInTimeZone(m.created_at, timeZone)}
                  {m.latency_ms != null && (
                    <span className="chat-panel__metrics">
                      {' '}（{m.token_per_sec != null ? `${m.token_per_sec.toFixed(1)} tokens/sec | ` : ''}latency {(m.latency_ms / 1000).toFixed(1)}s）
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
                  onClick={() => void copyAssistantMessageContent(m.content)}
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
            skipNextPersistRef.current = true
            clearChatPanelSnapshot()
            setMessages([])
            setLastLlmContext(null)
          }}
        >
          会話をクリア
        </button>
        <div
          className="chat-panel__sample-prompts"
          role="group"
          aria-label="サンプルの質問"
        >
          {visibleChatSamplePrompts.map((row) => (
            <button
              key={row.id}
              type="button"
              className="btn btn--gray chat-panel__sample-toggle"
              aria-label={`サンプル「${row.label}」`}
              disabled={loading}
              onClick={() => {
                setDraft((d) => appendChatSampleTextToDraft(d, row.text))
              }}
            >
              {row.label}
            </button>
          ))}
        </div>
        <div className="chat-panel__composer">
          <div className="chat-panel__composer-field">
            <label className="chat-panel__composer-label">
              メッセージ
              <textarea
                ref={draftTextareaRef}
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
          <button
            type="button"
            className="btn btn--gray chat-panel__icon-btn chat-panel__preview-btn"
            disabled={loading || previewing}
            aria-busy={previewing}
            aria-label={previewing ? 'プレビューを生成中' : 'プレビュー'}
            title={previewing ? 'プレビューを生成中' : 'プレビュー'}
            onClick={() => void previewPrompt()}
          >
            <ChatPreviewSvg />
          </button>
          <button
            type="button"
            className="btn btn--filled chat-panel__icon-btn chat-panel__send-btn"
            disabled={loading || previewing}
            aria-busy={loading}
            aria-label={loading ? '送信中' : '送信'}
            title={loading ? '送信中' : '送信'}
            onClick={() => void send()}
          >
            <ChatSendSvg />
          </button>
        </div>
      </div>
      {previewData && isPreviewModalOpen && (
        <ChatPromptPreviewModal
          preview={previewData}
          onClose={() => setIsPreviewModalOpen(false)}
        />
      )}
    </div>
  )
}
