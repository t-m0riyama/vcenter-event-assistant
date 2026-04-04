/**
 * チャットサンプル一覧を localStorage と同期し、チャット表示用のフィルタ済み一覧を提供する。
 */
import { useCallback, useMemo, useState, type ReactNode } from 'react'

import type { ChatSamplePromptRow } from '../panels/chat/chatSamplePromptTypes'
import { ChatCustomSamplePromptsContext } from './chatCustomSamplePromptsContext'
import { readStoredChatSamplePrompts, writeStoredChatSamplePrompts } from './chatSamplePromptsStorage'

function resolveInitial(): ChatSamplePromptRow[] {
  return readStoredChatSamplePrompts()
}

export function ChatCustomSamplePromptsProvider({ children }: { readonly children: ReactNode }) {
  const [chatSamplePrompts, setChatSamplePromptsState] = useState(resolveInitial)

  const setChatSamplePrompts = useCallback((rows: readonly ChatSamplePromptRow[]) => {
    const copy = rows.map((r) => ({ id: r.id, label: r.label, text: r.text }))
    writeStoredChatSamplePrompts(copy)
    setChatSamplePromptsState(copy)
  }, [])

  const visibleChatSamplePrompts = useMemo(
    () => chatSamplePrompts.filter((r) => r.label.trim().length > 0 && r.text.trim().length > 0),
    [chatSamplePrompts],
  )

  const value = useMemo(
    () => ({
      chatSamplePrompts,
      setChatSamplePrompts,
      visibleChatSamplePrompts,
    }),
    [chatSamplePrompts, setChatSamplePrompts, visibleChatSamplePrompts],
  )

  return (
    <ChatCustomSamplePromptsContext.Provider value={value}>{children}</ChatCustomSamplePromptsContext.Provider>
  )
}
