import { useCallback, useEffect, useRef, useState } from 'react'

import { apiGet, apiPost } from '../api'
import { buildIncidentTimelineBuildRequestPayload } from '../api/buildIncidentTimelineBuildRequestPayload'
import {
  parseChatResponse,
  parseChatPreviewResponse,
  type ChatLlmContextMeta,
  type ChatMessage,
  type ChatPreviewResponse,
  type VCenter,
} from '../api/schemas'
import { resolveEventApiRange } from '../datetime/graphRange'
import {
  zonedRangePartsToCombinedInputs,
} from '../datetime/zonedRangeParts'
import { useTimeZone } from '../datetime/useTimeZone'
import { useRollingZonedRangeParts } from './useRollingZonedRangeParts'
import { readStoredChatMaxStoredMessages } from '../preferences/chatMaxStoredMessagesStorage'
import { useChatMaxStoredMessages } from '../preferences/useChatMaxStoredMessages'
import {
  CHAT_LLM_CONTEXT_MAX_MESSAGES,
  clearChatPanelSnapshot,
  readChatPanelSnapshot,
  trimChatMessagesToMax,
  writeChatPanelSnapshot,
} from '../preferences/chatPanelStorage'
import { asArray } from '../utils/asArray'
import { toErrorMessage } from '../utils/errors'
import { usePeriodMetricThresholdFields } from './usePeriodMetricThresholdFields'

/** 下書きを localStorage に反映するまでの待機（入力のたびに書き込まない） */
const CHAT_DRAFT_PERSIST_DEBOUNCE_MS = 400

/**
 * チャットパネルの状態・localStorage 永続化・送信 / プレビュー API をまとめる。
 */
export function useChatPanelController(onError: (e: string | null) => void) {
  const { timeZone } = useTimeZone()
  const { chatMaxStoredMessages } = useChatMaxStoredMessages()
  const thresholdFields = usePeriodMetricThresholdFields()

  const { rangeParts, setRangeParts } = useRollingZonedRangeParts(timeZone)
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
  const [lastLlmContext, setLastLlmContext] = useState<ChatLlmContextMeta | null>(null)
  const [storageHydrated, setStorageHydrated] = useState(false)
  const [debouncedDraft, setDebouncedDraft] = useState('')
  const skipNextPersistRef = useRef(false)
  const storageWriteErrorReportedRef = useRef(false)
  const skipMaxTrimOnMountRef = useRef(true)
  const draftTextareaRef = useRef<HTMLTextAreaElement>(null)
  const sendInFlightRef = useRef(false)

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

  const buildChatRequestBody = useCallback(
    (nextMessages: ChatMessage[]) => {
      const { rangeFromInput, rangeToInput } = zonedRangePartsToCombinedInputs(rangeParts)
      const resolved = resolveEventApiRange(rangeFromInput, rangeToInput, timeZone)
      if (!resolved.ok) {
        return { ok: false as const, message: resolved.message }
      }
      if (!resolved.from || !resolved.to) {
        return { ok: false as const, message: '期間の開始と終了を指定してください。' }
      }
      return {
        ok: true as const,
        body: {
          ...buildIncidentTimelineBuildRequestPayload({
            resolvedRange: { from: resolved.from, to: resolved.to },
            options: {
              vcenterId,
              includePeriodMetricsCpu,
              includePeriodMetricsMemory,
              includePeriodMetricsDiskIo,
              includePeriodMetricsNetworkIo,
              metricThresholdCpuPct: thresholdFields.metricThresholdCpuPct,
              metricThresholdMemoryPct: thresholdFields.metricThresholdMemoryPct,
              metricThresholdDiskPct: thresholdFields.metricThresholdDiskPct,
              metricThresholdNetworkPct: thresholdFields.metricThresholdNetworkPct,
            },
          }),
          messages: trimChatMessagesToMax(nextMessages, CHAT_LLM_CONTEXT_MAX_MESSAGES).map(
            ({ role, content, created_at, latency_ms, token_per_sec }) => ({
              role,
              content,
              ...(created_at !== undefined ? { created_at } : {}),
              ...(latency_ms !== undefined ? { latency_ms } : {}),
              ...(token_per_sec !== undefined ? { token_per_sec } : {}),
            }),
          ),
        },
      }
    },
    [
      rangeParts,
      timeZone,
      vcenterId,
      includePeriodMetricsCpu,
      includePeriodMetricsMemory,
      includePeriodMetricsDiskIo,
      includePeriodMetricsNetworkIo,
      thresholdFields.metricThresholdCpuPct,
      thresholdFields.metricThresholdMemoryPct,
      thresholdFields.metricThresholdDiskPct,
      thresholdFields.metricThresholdNetworkPct,
    ],
  )

  const send = useCallback(async () => {
    const text = draft.trim()
    if (!text || sendInFlightRef.current) return

    const requestId = crypto.randomUUID()
    const nextMessages = trimChatMessagesToMax(
      [
        ...messages,
        {
          role: 'user',
          content: text,
          created_at: new Date().toISOString(),
          client_request_id: requestId,
        },
      ],
      chatMaxStoredMessages,
    )
    const built = buildChatRequestBody(nextMessages)
    if (!built.ok) {
      onError(built.message)
      return
    }

    onError(null)
    setMessages(nextMessages)
    setDraft('')
    setDebouncedDraft('')
    sendInFlightRef.current = true
    setLoading(true)
    try {
      const raw = await apiPost<unknown>('/api/chat', built.body)
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
      setMessages((m) => m.filter((msg) => msg.client_request_id !== requestId))
    } finally {
      sendInFlightRef.current = false
      setLoading(false)
    }
  }, [draft, messages, onError, buildChatRequestBody, chatMaxStoredMessages])

  const previewPrompt = useCallback(async () => {
    const text = draft.trim()
    if (!text) return

    const nextMessages = trimChatMessagesToMax(
      [...messages, { role: 'user', content: text }],
      chatMaxStoredMessages,
    )
    const built = buildChatRequestBody(nextMessages)
    if (!built.ok) {
      onError(built.message)
      return
    }

    onError(null)
    setPreviewing(true)
    try {
      const raw = await apiPost<unknown>('/api/chat/preview', built.body)
      const out = parseChatPreviewResponse(raw)
      setPreviewData(out)
      setIsPreviewModalOpen(true)
    } catch (e) {
      onError(toErrorMessage(e))
    } finally {
      setPreviewing(false)
    }
  }, [draft, messages, onError, buildChatRequestBody, chatMaxStoredMessages])

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

  const handleClearConversation = useCallback(() => {
    if (!window.confirm('会話をすべて削除しますか？')) return
    skipNextPersistRef.current = true
    clearChatPanelSnapshot()
    setMessages([])
    setLastLlmContext(null)
  }, [])

  const closePreviewModal = useCallback(() => {
    setIsPreviewModalOpen(false)
  }, [])

  return {
    timeZone,
    rangeParts,
    setRangeParts,
    vcenters,
    vcenterId,
    setVcenterId,
    messages,
    draft,
    setDraft,
    loading,
    previewing,
    previewData,
    isPreviewModalOpen,
    includePeriodMetricsCpu,
    setIncludePeriodMetricsCpu,
    includePeriodMetricsMemory,
    setIncludePeriodMetricsMemory,
    includePeriodMetricsDiskIo,
    setIncludePeriodMetricsDiskIo,
    includePeriodMetricsNetworkIo,
    setIncludePeriodMetricsNetworkIo,
    lastLlmContext,
    draftTextareaRef,
    ...thresholdFields,
    send,
    previewPrompt,
    copyAssistantMessageContent,
    handleClearConversation,
    closePreviewModal,
  }
}
