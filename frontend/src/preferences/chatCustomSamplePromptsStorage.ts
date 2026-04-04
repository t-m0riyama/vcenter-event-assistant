import { z } from 'zod'

import type { ChatSamplePromptRow } from '../panels/chat/chatSamplePromptTypes'

/** カスタムサンプル質問のみを保存する localStorage キー（既定サンプルは含めない）。 */
export const CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY = 'vea.chat_custom_sample_prompts.v1'

const rowSchema = z.object({
  id: z.string().min(1),
  label: z.string(),
  text: z.string(),
})

const arraySchema = z.array(rowSchema)

/**
 * 保存済みカスタムサンプルを読む。未設定・不正時は空配列。
 */
export function readStoredChatCustomSamplePrompts(): ChatSamplePromptRow[] {
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

/**
 * カスタムサンプル配列を保存する（Zod で検証してから JSON 化）。
 */
export function writeStoredChatCustomSamplePrompts(rows: readonly ChatSamplePromptRow[]): void {
  if (typeof localStorage === 'undefined') {
    return
  }
  const v = arraySchema.parse(rows)
  localStorage.setItem(CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY, JSON.stringify(v))
}
