import { z } from 'zod'

import type { ChatSamplePromptRow } from '../panels/chat/chatSamplePromptTypes'
import { getInitialChatSamplePromptsSnapshot } from '../panels/chat/defaultChatSamplePrompts'

/** チャットサンプル一覧（既定含む）を保存する localStorage キー。 */
export const CHAT_SAMPLE_PROMPTS_STORAGE_KEY = 'vea.chat_sample_prompts.v1'

/**
 * 旧実装のカスタムのみキー。移行時に読み取り後に削除する。
 * @deprecated 新コードでは {@link CHAT_SAMPLE_PROMPTS_STORAGE_KEY} のみを使う。
 */
export const CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY = 'vea.chat_custom_sample_prompts.v1'

const rowSchema = z.object({
  id: z.string().min(1),
  label: z.string(),
  text: z.string(),
})

const arraySchema = z.array(rowSchema)

function seedFromInitialAndLegacy(legacyRows: readonly ChatSamplePromptRow[]): ChatSamplePromptRow[] {
  const initial = getInitialChatSamplePromptsSnapshot()
  const seen = new Set(initial.map((r) => r.id))
  const merged = [...initial]
  for (const row of legacyRows) {
    if (!seen.has(row.id)) {
      merged.push({ id: row.id, label: row.label, text: row.text })
      seen.add(row.id)
    }
  }
  return merged
}

function readLegacyCustomOnly(): ChatSamplePromptRow[] {
  if (typeof localStorage === 'undefined') {
    return []
  }
  const raw = localStorage.getItem(CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY)
  if (raw === null) {
    return []
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(raw) as unknown
  } catch {
    return []
  }
  const out = arraySchema.safeParse(parsed)
  return out.success ? out.data : []
}

function removeLegacyKey(): void {
  if (typeof localStorage === 'undefined') {
    return
  }
  localStorage.removeItem(CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY)
}

/**
 * 保存済みチャットサンプル一覧を読む。未設定時は INITIAL をシードして保存する。
 * 旧キー（カスタムのみ）のみある場合は INITIAL とマージして新キーへ移行する。
 */
export function readStoredChatSamplePrompts(): ChatSamplePromptRow[] {
  if (typeof localStorage === 'undefined') {
    return []
  }

  const rawNew = localStorage.getItem(CHAT_SAMPLE_PROMPTS_STORAGE_KEY)
  if (rawNew !== null) {
    let parsed: unknown
    try {
      parsed = JSON.parse(rawNew) as unknown
    } catch {
      localStorage.removeItem(CHAT_SAMPLE_PROMPTS_STORAGE_KEY)
      const migrated = seedFromInitialAndLegacy(readLegacyCustomOnly())
      writeStoredChatSamplePromptsInternal(migrated)
      removeLegacyKey()
      return migrated
    }
    const out = arraySchema.safeParse(parsed)
    if (out.success) {
      removeLegacyKey()
      return out.data
    }
    localStorage.removeItem(CHAT_SAMPLE_PROMPTS_STORAGE_KEY)
  }

  const legacy = readLegacyCustomOnly()
  const migrated = seedFromInitialAndLegacy(legacy)
  writeStoredChatSamplePromptsInternal(migrated)
  removeLegacyKey()
  return migrated
}

function writeStoredChatSamplePromptsInternal(rows: readonly ChatSamplePromptRow[]): void {
  if (typeof localStorage === 'undefined') {
    return
  }
  const v = arraySchema.parse(rows)
  localStorage.setItem(CHAT_SAMPLE_PROMPTS_STORAGE_KEY, JSON.stringify(v))
}

/**
 * チャットサンプル一覧を保存する（Zod で検証してから JSON 化）。
 */
export function writeStoredChatSamplePrompts(rows: readonly ChatSamplePromptRow[]): void {
  writeStoredChatSamplePromptsInternal(rows)
}
