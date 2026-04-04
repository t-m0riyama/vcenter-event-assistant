import { z } from 'zod'

import { chatMessageSchema, type ChatMessage } from '../api/schemas'

/** チャットパネル状態を保存する localStorage キー。 */
export const CHAT_PANEL_STORAGE_KEY = 'vea.chat_panel.v1'

/**
 * ブラウザに保持する会話メッセージの既定上限（`ChatMessage` 配列の長さ）。
 * 超えた分は先頭から欠落（FIFO）。ユーザー設定で上書きする拡張は別タスク。
 */
export const DEFAULT_CHAT_MAX_STORED_MESSAGES = 200

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
  vcenterId: z.string(),
  includePeriodMetricsCpu: z.boolean(),
  includePeriodMetricsMemory: z.boolean(),
  includePeriodMetricsDiskIo: z.boolean(),
  includePeriodMetricsNetworkIo: z.boolean(),
  draft: z.string(),
})

export type ChatPanelSnapshot = z.infer<typeof chatPanelSnapshotSchema>

/**
 * 会話メッセージを最大件数に収める。超過分は先頭から削除する（FIFO）。
 */
export function trimChatMessagesToMax(
  messages: readonly ChatMessage[],
  max: number,
): ChatMessage[] {
  if (messages.length <= max) {
    return [...messages]
  }
  return messages.slice(-max)
}

function trimSnapshotMessages(snapshot: ChatPanelSnapshot): ChatPanelSnapshot {
  return {
    ...snapshot,
    messages: trimChatMessagesToMax(snapshot.messages, DEFAULT_CHAT_MAX_STORED_MESSAGES),
  }
}

/**
 * 保存済みチャットパネル状態を読む。未設定・不正時は `null`（不正キーは削除する）。
 */
export function readChatPanelSnapshot(): ChatPanelSnapshot | null {
  if (typeof localStorage === 'undefined') {
    return null
  }
  const raw = localStorage.getItem(CHAT_PANEL_STORAGE_KEY)
  if (raw === null) {
    return null
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(raw) as unknown
  } catch {
    localStorage.removeItem(CHAT_PANEL_STORAGE_KEY)
    return null
  }
  const out = chatPanelSnapshotSchema.safeParse(parsed)
  if (!out.success) {
    localStorage.removeItem(CHAT_PANEL_STORAGE_KEY)
    return null
  }
  return {
    ...out.data,
    messages: trimChatMessagesToMax(out.data.messages, DEFAULT_CHAT_MAX_STORED_MESSAGES),
  }
}

/**
 * チャットパネル状態を保存する。`messages` は既定上限でトリムしてから検証・保存する。
 *
 * @returns 保存に成功したとき `true`。`localStorage` が無い・`setItem` が失敗したとき `false`。
 */
export function writeChatPanelSnapshot(snapshot: ChatPanelSnapshot): boolean {
  if (typeof localStorage === 'undefined') {
    return false
  }
  try {
    const trimmed = trimSnapshotMessages(snapshot)
    const v = chatPanelSnapshotSchema.parse(trimmed)
    localStorage.setItem(CHAT_PANEL_STORAGE_KEY, JSON.stringify(v))
    return true
  } catch {
    return false
  }
}

/**
 * 保存したチャットパネル状態を削除する。
 */
export function clearChatPanelSnapshot(): void {
  if (typeof localStorage === 'undefined') {
    return
  }
  localStorage.removeItem(CHAT_PANEL_STORAGE_KEY)
}
