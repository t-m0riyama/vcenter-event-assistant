import { createContext } from 'react'

import type { ChatSamplePromptRow } from '../panels/chat/chatSamplePromptTypes'

/** チャット用カスタムサンプル質問の Context 値。 */
export type ChatCustomSamplePromptsContextValue = {
  readonly customSamplePrompts: readonly ChatSamplePromptRow[]
  readonly setCustomSamplePrompts: (rows: readonly ChatSamplePromptRow[]) => void
  /** チャットチップ用: 既定＋カスタムのうち label・text が非空の行のみ。 */
  readonly visibleChatSamplePrompts: readonly ChatSamplePromptRow[]
}

export const ChatCustomSamplePromptsContext =
  createContext<ChatCustomSamplePromptsContextValue | null>(null)
