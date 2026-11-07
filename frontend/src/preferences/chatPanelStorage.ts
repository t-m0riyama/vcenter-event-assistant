import { z } from 'zod'

import { chatMessageSchema, type ChatMessage } from '../api/schemas'

/** チャットパネル状態を保存する sessionStorage キー（共有端末向けに localStorage より安全）。 */
export const CHAT_PANEL_STORAGE_KEY = 'vea.chat_panel.v2'
const LEGACY_STORAGE_KEY = 'vea.chat_panel.v1'
export const AUTH_DISABLED_CHAT_OWNER = 'auth-disabled'

/** 所有者が同じ値に戻っても、古い画面の参照は有効にならない。 */
export type ChatStorageScope = Readonly<{ owner: string }>
let activeScope: ChatStorageScope | null = null
let canRestore = true

export function isActiveChatScope(scope: ChatStorageScope | null): scope is ChatStorageScope {
  return scope !== null && scope === activeScope
}

/** 画面が外れた後の処理を無効にし、同じセッションの再読み込み用データは残す。 */
export function releaseChatScope(scope: ChatStorageScope | null): void {
  if (isActiveChatScope(scope)) activeScope = null
}

export { DEFAULT_CHAT_MAX_STORED_MESSAGES } from './chatMaxStoredMessagesStorage'

/**
 * バックエンド `chat_llm._MAX_CHAT_MESSAGES` と同値。LLM に渡る会話は直近この件数まで。
 * フロントの `POST /api/chat` 本文の `messages` もこの件数に収め、帯域とサーバー側トリムと揃える。
 */
export const CHAT_LLM_CONTEXT_MAX_MESSAGES = 20

const zonedRangePartsSchema = z.object({
  fromDate: z.string(),
  fromTime: z.string(),
  toDate: z.string(),
  toTime: z.string(),
})

const chatPanelSnapshotSchema = z.object({
  messages: z.array(chatMessageSchema),
  rangeParts: zonedRangePartsSchema,
  /** 「直近 N」で選んだときの N（ミリ秒）。手入力なら null。前の版の保存データにはない（手入力として戻す）。 */
  rollingDurationMs: z.number().positive().nullable().optional(),
  vcenterId: z.string(),
  includePeriodMetricsCpu: z.boolean(),
  includePeriodMetricsMemory: z.boolean(),
  includePeriodMetricsDiskIo: z.boolean(),
  includePeriodMetricsNetworkIo: z.boolean(),
  draft: z.string(),
})

export type ChatPanelSnapshot = z.infer<typeof chatPanelSnapshotSchema>
const storedSnapshotSchema = chatPanelSnapshotSchema.extend({ owner: z.string() })

function removeSnapshot(): void {
  try {
    sessionStorage.removeItem(CHAT_PANEL_STORAGE_KEY)
    canRestore = true
  } catch {
    canRestore = false
  }
}

export function activateChatScope(owner: string | null): ChatStorageScope | null {
  if (owner !== null && activeScope?.owner === owner) return activeScope
  const hadScope = activeScope !== null
  activeScope = owner === null ? null : { owner }
  try {
    sessionStorage.removeItem(LEGACY_STORAGE_KEY)
  } catch {
    // 旧形式は復元対象に含めない。
  }
  try {
    localStorage.removeItem(LEGACY_STORAGE_KEY)
  } catch {
    // 以前の localStorage 保存も、利用可能な場合にだけ削除する。
  }
  if (activeScope === null || hadScope) {
    removeSnapshot()
  } else {
    // パネルが開かれていなくても、別セッションのデータは破棄する。
    readChatPanelSnapshot(activeScope, 0)
  }
  return activeScope
}

/**
 * 会話メッセージを最大件数に収める。超過分は先頭から削除する（FIFO）。
 */
export function trimChatMessagesToMax(
  messages: readonly ChatMessage[],
  max: number,
): ChatMessage[] {
  if (max <= 0) {
    return []
  }
  if (messages.length <= max) {
    return [...messages]
  }
  return messages.slice(-max)
}

function trimSnapshotMessages(snapshot: ChatPanelSnapshot, maxStoredMessages: number): ChatPanelSnapshot {
  return {
    ...snapshot,
    messages: trimChatMessagesToMax(snapshot.messages, maxStoredMessages),
  }
}

/**
 * 保存済みチャットパネル状態を読む。未設定・不正時は `null`（不正キーは削除する）。
 *
 * @param maxStoredMessages 会話メッセージの最大件数（ユーザー設定 0〜1000。0 は常に空配列）。
 */
export function readChatPanelSnapshot(
  scope: ChatStorageScope | null,
  maxStoredMessages: number,
): ChatPanelSnapshot | null {
  if (!isActiveChatScope(scope) || !canRestore) return null
  try {
    const raw = sessionStorage.getItem(CHAT_PANEL_STORAGE_KEY)
    if (raw === null) return null
    const out = storedSnapshotSchema.safeParse(JSON.parse(raw) as unknown)
    if (out.success) {
      const { owner, ...snapshot } = out.data
      if (owner === scope.owner) return trimSnapshotMessages(snapshot, maxStoredMessages)
    }
  } catch {
    // 取得・解析に失敗した状態は復元しない。
  }
  removeSnapshot()
  return null
}

/**
 * チャットパネル状態を保存する。`messages` は `maxStoredMessages` でトリムしてから検証・保存する。
 *
 * 無効なスコープからの保存はスキップする。
 */
export function writeChatPanelSnapshot(
  scope: ChatStorageScope | null,
  snapshot: ChatPanelSnapshot,
  maxStoredMessages: number,
): 'saved' | 'skipped' | 'failed' {
  if (!isActiveChatScope(scope)) return 'skipped'
  try {
    const trimmed = trimSnapshotMessages(snapshot, maxStoredMessages)
    const v = storedSnapshotSchema.parse({ ...trimmed, owner: scope.owner })
    sessionStorage.setItem(CHAT_PANEL_STORAGE_KEY, JSON.stringify(v))
    canRestore = true
    return 'saved'
  } catch {
    return 'failed'
  }
}

/**
 * 保存したチャットパネル状態を削除する。
 */
export function clearChatPanelSnapshot(scope: ChatStorageScope | null): void {
  if (isActiveChatScope(scope)) removeSnapshot()
}
