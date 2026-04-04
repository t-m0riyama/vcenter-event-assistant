/**
 * カスタムチャットサンプルを localStorage と同期し、チャット表示用の合成一覧を提供する。
 */
import { useCallback, useMemo, useState, type ReactNode } from 'react'

import type { ChatSamplePromptRow } from '../panels/chat/chatSamplePromptTypes'
import { DEFAULT_CHAT_SAMPLE_PROMPTS } from '../panels/chat/defaultChatSamplePrompts'
import { ChatCustomSamplePromptsContext } from './chatCustomSamplePromptsContext'
import {
  readStoredChatCustomSamplePrompts,
  writeStoredChatCustomSamplePrompts,
} from './chatCustomSamplePromptsStorage'

function resolveInitialCustom(): ChatSamplePromptRow[] {
  return readStoredChatCustomSamplePrompts()
}

export function ChatCustomSamplePromptsProvider({ children }: { readonly children: ReactNode }) {
  const [customSamplePrompts, setCustomSamplePromptsState] = useState(resolveInitialCustom)

  const setCustomSamplePrompts = useCallback((rows: readonly ChatSamplePromptRow[]) => {
    const copy = rows.map((r) => ({ id: r.id, label: r.label, text: r.text }))
    writeStoredChatCustomSamplePrompts(copy)
    setCustomSamplePromptsState(copy)
  }, [])

  const visibleChatSamplePrompts = useMemo(() => {
    const merged = [...DEFAULT_CHAT_SAMPLE_PROMPTS, ...customSamplePrompts]
    return merged.filter((r) => r.label.trim().length > 0 && r.text.trim().length > 0)
  }, [customSamplePrompts])

  const value = useMemo(
    () => ({
      customSamplePrompts,
      setCustomSamplePrompts,
      visibleChatSamplePrompts,
    }),
    [customSamplePrompts, setCustomSamplePrompts, visibleChatSamplePrompts],
  )

  return (
    <ChatCustomSamplePromptsContext.Provider value={value}>{children}</ChatCustomSamplePromptsContext.Provider>
  )
}
