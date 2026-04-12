import { createContext } from 'react'

import type { ChatSamplePromptRow } from '../panels/chat/chatSamplePromptTypes'

/** プロンプトスニペット質問の Context 値（localStorage と同期する全行）。 */
export type ChatSamplePromptsContextValue = {
  /** 保存済みの全サンプル行（既定由来の行も含む）。 */
  readonly chatSamplePrompts: readonly ChatSamplePromptRow[]
  readonly setChatSamplePrompts: (rows: readonly ChatSamplePromptRow[]) => void
  /** チャットチップ用: label・text がともに非空（trim 後）の行のみ。 */
  readonly visibleChatSamplePrompts: readonly ChatSamplePromptRow[]
}

export const ChatSamplePromptsContext = createContext<ChatSamplePromptsContextValue | null>(null)
