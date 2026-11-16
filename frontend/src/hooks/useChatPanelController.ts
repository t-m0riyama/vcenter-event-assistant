import { useCallback, useEffect, useRef, useState } from 'react'

import { apiGet, apiPost } from '../api'
import { validateApiRange } from '../datetime/apiRangeLimit'
import { useAuth } from '../auth/useAuth'
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
  zonedRangePartsFromUtcIsoEndpoints,
  zonedRangePartsToCombinedInputs,
} from '../datetime/zonedRangeParts'
import type { ChatHandoffInput } from './chatHandoff'
import type { ChatExactRange } from '../preferences/chatPanelStorage'

/** 引き継ぎの注記に出す内容。 */
export type ChatHandoffNote = {
  narrowedBy: string[]
  fromSavedSnapshot: boolean
  hadConversation: boolean
}
import { useTimeZone } from '../datetime/useTimeZone'
import { useRollingZonedRangeParts } from './useRollingZonedRangeParts'
import { readStoredChatMaxStoredMessages } from '../preferences/chatMaxStoredMessagesStorage'
import { useChatMaxStoredMessages } from '../preferences/useChatMaxStoredMessages'
import { useChatWebSearchPrefs } from '../preferences/useChatWebSearchPrefs'
import {
  CHAT_LLM_CONTEXT_MAX_MESSAGES,
  clearChatPanelSnapshot,
  isActiveChatScope,
  readChatPanelSnapshot,
  trimChatMessagesToMax,
  writeChatPanelSnapshot,
} from '../preferences/chatPanelStorage'
import { asArray } from '../utils/asArray'
import { toErrorMessage } from '../utils/errors'
import { randomId } from '../utils/randomId'
import { usePeriodMetricThresholdFields } from './usePeriodMetricThresholdFields'
import { hasBlockingChatAttachment } from '../panels/chat/attachments/buildChatAttachmentPayloads'
import { useChatAttachments } from '../panels/chat/attachments/useChatAttachments'
import {
  DEFAULT_CHAT_ATTACHMENT_LIMITS,
  type ChatAttachmentLimits,
  type ChatAttachmentPayload,
} from '../panels/chat/attachments/chatAttachmentTypes'

/** 下書きを sessionStorage に反映するまでの待機（入力のたびに書き込まない） */
const CHAT_DRAFT_PERSIST_DEBOUNCE_MS = 400

/**
 * チャットパネルの状態・セッション内の保存・送信 / プレビュー API をまとめる。
 */
export function useChatPanelController(
  onError: (e: string | null) => void,
  handoff: ChatHandoffInput | null = null,
  onHandoffApplied?: () => void,
) {
  const { chatStorageScope = null } = useAuth()
  const { timeZone } = useTimeZone()
  const { chatMaxStoredMessages } = useChatMaxStoredMessages()
  const { prefs: webSearchPrefs } = useChatWebSearchPrefs()
  const thresholdFields = usePeriodMetricThresholdFields()

  const {
    rangeParts,
    setRangeParts,
    applyRollingPreset,
    restoreRange,
    rangeDisplayLabel,
    activeRollingDurationMs,
  } = useRollingZonedRangeParts(timeZone)
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
  const [enableWebSearch, setEnableWebSearch] = useState(false)
  const [webSearchAvailable, setWebSearchAvailable] = useState(false)
  const [attachmentLimits, setAttachmentLimits] = useState<ChatAttachmentLimits>(
    DEFAULT_CHAT_ATTACHMENT_LIMITS,
  )
  const [lastLlmContext, setLastLlmContext] = useState<ChatLlmContextMeta | null>(null)
  const [storageHydrated, setStorageHydrated] = useState(false)
  /** タイムラインから期間を引き継いだことの注記。閉じる・会話のクリア・次の引き継ぎまで残す。 */
  const [handoffNote, setHandoffNote] = useState<ChatHandoffNote | null>(null)
  /** 引き継いだ期間の正確な端点。部品を編集するまで、送信でそのまま使う（分単位の部品に丸めない）。 */
  const [exactRange, setExactRange] = useState<ChatExactRange | null>(null)
  const appliedHandoffRef = useRef(0)
  const messagesRef = useRef<ChatMessage[]>([])
  const [debouncedDraft, setDebouncedDraft] = useState('')
  const skipNextPersistRef = useRef(false)
  const storageWriteErrorReportedRef = useRef(false)
  const skipMaxTrimOnMountRef = useRef(true)
  const draftTextareaRef = useRef<HTMLTextAreaElement>(null)
  const sendInFlightRef = useRef(false)
  const {
    attachments,
    addFiles,
    removeAttachment,
    clearAttachments,
    restoreAttachments,
    attachmentPayloads,
  } = useChatAttachments(attachmentLimits)

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
    // WEB 検索の利用可否と添付の上限（取得失敗時は静かに既定のまま）
    void (async () => {
      try {
        const raw = (await apiGet<unknown>('/api/config')) as {
          chat_web_search_available?: boolean
          chat_attachment_images_available?: boolean
          chat_attachment_max_files?: number
          chat_attachment_max_file_bytes?: number
          chat_attachment_max_text_chars?: number
        }
        setWebSearchAvailable(raw?.chat_web_search_available === true)
        setAttachmentLimits({
          maxFiles: raw?.chat_attachment_max_files ?? DEFAULT_CHAT_ATTACHMENT_LIMITS.maxFiles,
          maxFileBytes:
            raw?.chat_attachment_max_file_bytes ?? DEFAULT_CHAT_ATTACHMENT_LIMITS.maxFileBytes,
          maxTextChars:
            raw?.chat_attachment_max_text_chars ?? DEFAULT_CHAT_ATTACHMENT_LIMITS.maxTextChars,
          imagesAvailable: raw?.chat_attachment_images_available === true,
        })
      } catch {
        setWebSearchAvailable(false)
      }
    })()
  }, [])

  useEffect(() => {
    const id = window.setTimeout(() => {
      if (isActiveChatScope(chatStorageScope)) setDebouncedDraft(draft)
    }, CHAT_DRAFT_PERSIST_DEBOUNCE_MS)
    return () => window.clearTimeout(id)
  }, [draft, chatStorageScope])

  useEffect(() => {
    const max = readStoredChatMaxStoredMessages()
    const snap = readChatPanelSnapshot(chatStorageScope, max)
    if (snap) {
      restoreRange(snap.rangeParts, snap.rollingDurationMs ?? null)
      setExactRange(snap.exactRange ?? null)
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
  }, [restoreRange, chatStorageScope])

  messagesRef.current = messages

  // タイムラインからの引き継ぎ: 期間と vCenter だけを差し替える（下書き・会話・添付・ほかの条件は触らない）。
  // 保存済みの状態の読み込みより後に当てるため、読み込み完了を待つ。送信はしない。
  useEffect(() => {
    if (!storageHydrated || !handoff || handoff.nonce < 1) return
    if (appliedHandoffRef.current === handoff.nonce) return
    appliedHandoffRef.current = handoff.nonce
    const { from, to, vcenterId: nextVcenterId, narrowedBy, fromSavedSnapshot } = handoff.focus
    const invalid = validateApiRange({ from, to })
    if (invalid) {
      onError(`タイムラインの期間をチャットに引き継げませんでした。${invalid}`)
      onHandoffApplied?.()
      return
    }
    const parts = zonedRangePartsFromUtcIsoEndpoints(from, to, timeZone)
    restoreRange(parts, null)
    setExactRange({ from, to, timeZone, parts })
    setVcenterId(nextVcenterId ?? '')
    setHandoffNote({ narrowedBy, fromSavedSnapshot, hadConversation: messagesRef.current.length > 0 })
    onHandoffApplied?.()
  }, [handoff, onError, onHandoffApplied, restoreRange, storageHydrated, timeZone])

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
    const result = writeChatPanelSnapshot(
      chatStorageScope,
      {
        messages,
        rangeParts,
        rollingDurationMs: activeRollingDurationMs,
        exactRange,
        vcenterId,
        includePeriodMetricsCpu,
        includePeriodMetricsMemory,
        includePeriodMetricsDiskIo,
        includePeriodMetricsNetworkIo,
        draft: debouncedDraft,
      },
      chatMaxStoredMessages,
    )
    if (result === 'saved') {
      storageWriteErrorReportedRef.current = false
    } else if (result === 'failed' && !storageWriteErrorReportedRef.current) {
      storageWriteErrorReportedRef.current = true
      onError('ブラウザの保存領域が不足しているため、会話の保存に失敗しました。')
    }
  }, [
    storageHydrated,
    chatStorageScope,
    messages,
    rangeParts,
    activeRollingDurationMs,
    exactRange,
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
    (nextMessages: ChatMessage[], nextAttachments: ChatAttachmentPayload[] = []) => {
      const { rangeFromInput, rangeToInput } = zonedRangePartsToCombinedInputs(rangeParts)
      // 引き継いだ期間は、部品（分単位）を編集していない側の端点を、そのままの値で使う。
      // 壁時計からの組み直し（と、その検査）は、編集した側だけにかける（夏時間の戻りでは、
      // 壁時計の上で終了が開始より前に見える正しい期間がある）。順序と 90 日は、送る UTC の範囲で検査する。
      const exact = exactRange !== null && exactRange.timeZone === timeZone ? exactRange : null
      const fromExact =
        exact !== null && rangeParts.fromDate === exact.parts.fromDate && rangeParts.fromTime === exact.parts.fromTime
      const toExact =
        exact !== null && rangeParts.toDate === exact.parts.toDate && rangeParts.toTime === exact.parts.toTime
      const resolved = resolveEventApiRange(
        fromExact ? '' : rangeFromInput,
        toExact ? '' : rangeToInput,
        timeZone,
      )
      if (!resolved.ok) {
        return { ok: false as const, message: resolved.message }
      }
      const from = fromExact ? exact?.from : resolved.from
      const to = toExact ? exact?.to : resolved.to
      if (!from || !to) {
        return { ok: false as const, message: '期間の開始と終了を指定してください。' }
      }
      const invalid = validateApiRange({ from, to })
      if (invalid) {
        return { ok: false as const, message: invalid }
      }
      return {
        ok: true as const,
        body: {
          ...buildIncidentTimelineBuildRequestPayload({
            resolvedRange: { from, to },
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
          enable_web_search: webSearchAvailable && enableWebSearch,
          ...(webSearchAvailable && enableWebSearch
            ? {
                web_search_scope: webSearchPrefs.scope,
                web_search_aggressiveness: webSearchPrefs.aggressiveness,
              }
            : {}),
          ...(nextAttachments.length > 0 ? { attachments: nextAttachments } : {}),
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
      exactRange,
      timeZone,
      vcenterId,
      includePeriodMetricsCpu,
      includePeriodMetricsMemory,
      includePeriodMetricsDiskIo,
      includePeriodMetricsNetworkIo,
      enableWebSearch,
      webSearchAvailable,
      webSearchPrefs.scope,
      webSearchPrefs.aggressiveness,
      thresholdFields.metricThresholdCpuPct,
      thresholdFields.metricThresholdMemoryPct,
      thresholdFields.metricThresholdDiskPct,
      thresholdFields.metricThresholdNetworkPct,
    ],
  )

  const send = useCallback(async () => {
    if (!isActiveChatScope(chatStorageScope)) return
    const text = draft.trim()
    if (!text || sendInFlightRef.current) return
    if (hasBlockingChatAttachment(attachments)) {
      onError('添付ファイルの読み取りが終わっていないか、エラーがあります。')
      return
    }

    const payloads = attachmentPayloads()
    const restorable = attachments
    const requestId = randomId()
    const nextMessages = trimChatMessagesToMax(
      [
        ...messages,
        {
          role: 'user',
          content: text,
          created_at: new Date().toISOString(),
          client_request_id: requestId,
          ...(payloads.length > 0
            ? { attachment_names: payloads.map((a) => a.filename) }
            : {}),
        },
      ],
      chatMaxStoredMessages,
    )
    const built = buildChatRequestBody(nextMessages, payloads)
    if (!built.ok) {
      onError(built.message)
      return
    }

    onError(null)
    setMessages(nextMessages)
    setDraft('')
    setDebouncedDraft('')
    // 添付は送信したターン限り。失敗時は下のロールバックで戻す
    clearAttachments()
    sendInFlightRef.current = true
    setLoading(true)
    try {
      if (!isActiveChatScope(chatStorageScope)) return
      const raw = await apiPost<unknown>('/api/chat', built.body, chatStorageScope.owner.replace(/^session:/, ''))
      if (!isActiveChatScope(chatStorageScope)) return
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
      if (!isActiveChatScope(chatStorageScope)) return
      onError(toErrorMessage(e))
      setMessages((m) => m.filter((msg) => msg.client_request_id !== requestId))
      restoreAttachments(restorable)
    } finally {
      if (isActiveChatScope(chatStorageScope)) {
        sendInFlightRef.current = false
        setLoading(false)
      }
    }
  }, [
    chatStorageScope,
    draft,
    messages,
    onError,
    buildChatRequestBody,
    chatMaxStoredMessages,
    attachments,
    attachmentPayloads,
    clearAttachments,
    restoreAttachments,
  ])

  const previewPrompt = useCallback(async () => {
    if (!isActiveChatScope(chatStorageScope)) return
    const text = draft.trim()
    if (!text) return

    const nextMessages = trimChatMessagesToMax(
      [...messages, { role: 'user', content: text }],
      chatMaxStoredMessages,
    )
    const built = buildChatRequestBody(nextMessages, attachmentPayloads())
    if (!built.ok) {
      onError(built.message)
      return
    }

    onError(null)
    setPreviewing(true)
    try {
      if (!isActiveChatScope(chatStorageScope)) return
      const raw = await apiPost<unknown>('/api/chat/preview', built.body, chatStorageScope.owner.replace(/^session:/, ''))
      if (!isActiveChatScope(chatStorageScope)) return
      const out = parseChatPreviewResponse(raw)
      setPreviewData(out)
      setIsPreviewModalOpen(true)
    } catch (e) {
      if (isActiveChatScope(chatStorageScope)) onError(toErrorMessage(e))
    } finally {
      if (isActiveChatScope(chatStorageScope)) setPreviewing(false)
    }
  }, [
    chatStorageScope,
    draft,
    messages,
    onError,
    buildChatRequestBody,
    chatMaxStoredMessages,
    attachmentPayloads,
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

  const handleClearConversation = useCallback(() => {
    if (!isActiveChatScope(chatStorageScope)) return
    if (!window.confirm('会話をすべて削除しますか？')) return
    skipNextPersistRef.current = true
    clearChatPanelSnapshot(chatStorageScope)
    setMessages([])
    setHandoffNote(null)
    setLastLlmContext(null)
  }, [chatStorageScope])

  const closePreviewModal = useCallback(() => {
    setIsPreviewModalOpen(false)
  }, [])

  return {
    canSend: chatStorageScope !== null,
    handoffNote,
    dismissHandoffNote: () => setHandoffNote(null),
    timeZone,
    rangeParts,
    setRangeParts,
    applyRollingPreset,
    rangeDisplayLabel,
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
    enableWebSearch,
    setEnableWebSearch,
    webSearchAvailable,
    attachments,
    attachmentLimits,
    addAttachmentFiles: addFiles,
    removeAttachment,
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
