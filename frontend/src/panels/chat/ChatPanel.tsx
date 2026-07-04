import { useCallback, useEffect, useRef, useState } from 'react'
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
  CHAT_LLM_CONTEXT_MAX_MESSAGES,
  clearChatPanelSnapshot,
  readChatPanelSnapshot,
  trimChatMessagesToMax,
  writeChatPanelSnapshot,
} from '../../preferences/chatPanelStorage'
import { ChatContextBar } from './ChatContextBar'
import { ChatInputBar } from './ChatInputBar'
import { ChatMessagesList } from './ChatMessagesList'
import { ChatPromptPreviewModal } from './ChatPromptPreviewModal'

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
  const [storageHydrated, setStorageHydrated] = useState(false)
  const [debouncedDraft, setDebouncedDraft] = useState('')
  const skipNextPersistRef = useRef(false)
  const storageWriteErrorReportedRef = useRef(false)
  const skipMaxTrimOnMountRef = useRef(true)
  const draftTextareaRef = useRef<HTMLTextAreaElement>(null)

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

  const handleClearConversation = () => {
    if (!window.confirm('会話をすべて削除しますか？')) return
    skipNextPersistRef.current = true
    clearChatPanelSnapshot()
    setMessages([])
    setLastLlmContext(null)
  }

  return (
    <div className="panel chat-panel">
      <p className="hint">
        指定期間のイベント・メトリクス集約を根拠に、質問・追質問ができます（会話はブラウザに保持し、サーバーは保存しません）。
      </p>

      <ChatContextBar
        rangeParts={rangeParts}
        setRangeParts={setRangeParts}
        vcenters={vcenters}
        vcenterId={vcenterId}
        setVcenterId={setVcenterId}
        loading={loading}
        includePeriodMetricsCpu={includePeriodMetricsCpu}
        setIncludePeriodMetricsCpu={setIncludePeriodMetricsCpu}
        includePeriodMetricsMemory={includePeriodMetricsMemory}
        setIncludePeriodMetricsMemory={setIncludePeriodMetricsMemory}
        includePeriodMetricsDiskIo={includePeriodMetricsDiskIo}
        setIncludePeriodMetricsDiskIo={setIncludePeriodMetricsDiskIo}
        includePeriodMetricsNetworkIo={includePeriodMetricsNetworkIo}
        setIncludePeriodMetricsNetworkIo={setIncludePeriodMetricsNetworkIo}
        metricThresholdCpuInput={metricThresholdCpuInput}
        metricThresholdCpuPct={metricThresholdCpuPct}
        setMetricThresholdCpuInput={setMetricThresholdCpuInput}
        setMetricThresholdCpuPct={setMetricThresholdCpuPct}
        metricThresholdMemoryInput={metricThresholdMemoryInput}
        metricThresholdMemoryPct={metricThresholdMemoryPct}
        setMetricThresholdMemoryInput={setMetricThresholdMemoryInput}
        setMetricThresholdMemoryPct={setMetricThresholdMemoryPct}
        metricThresholdDiskInput={metricThresholdDiskInput}
        metricThresholdDiskPct={metricThresholdDiskPct}
        setMetricThresholdDiskInput={setMetricThresholdDiskInput}
        setMetricThresholdDiskPct={setMetricThresholdDiskPct}
        metricThresholdNetworkInput={metricThresholdNetworkInput}
        metricThresholdNetworkPct={metricThresholdNetworkPct}
        setMetricThresholdNetworkInput={setMetricThresholdNetworkInput}
        setMetricThresholdNetworkPct={setMetricThresholdNetworkPct}
        onMetricThresholdInputChange={handleMetricThresholdInputChange}
      />

      <ChatMessagesList
        messages={messages}
        loading={loading}
        timeZone={timeZone}
        onCopyAssistantMessage={copyAssistantMessageContent}
      />

      {lastLlmContext != null && (
        <p className="hint chat-panel__llm-meta" role="status" aria-live="polite">
          LLM 入力（目安）: 推定 {lastLlmContext.estimated_input_tokens} / {lastLlmContext.max_input_tokens}{' '}
          トークン
          {lastLlmContext.json_truncated ? '・JSON 切り詰めあり' : '・JSON 切り詰めなし'}
          ・会話 {lastLlmContext.message_turns} ターン（トリム後）
        </p>
      )}

      <ChatInputBar
        loading={loading}
        previewing={previewing}
        hasMessages={messages.length > 0}
        visibleChatSamplePrompts={visibleChatSamplePrompts}
        draft={draft}
        setDraft={setDraft}
        draftTextareaRef={draftTextareaRef}
        onClearConversation={handleClearConversation}
        onSend={send}
        onPreview={previewPrompt}
      />

      {previewData && isPreviewModalOpen && (
        <ChatPromptPreviewModal
          preview={previewData}
          onClose={() => setIsPreviewModalOpen(false)}
        />
      )}
    </div>
  )
}
