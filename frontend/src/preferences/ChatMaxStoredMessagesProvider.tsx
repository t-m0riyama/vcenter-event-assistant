/**
 * チャット会話の最大保持件数（0〜1000）を Context と localStorage で共有する。
 */
import { useCallback, useMemo, useState, type ReactNode } from 'react'

import { ChatMaxStoredMessagesContext } from './chatMaxStoredMessagesContext'
import {
  clampChatMaxStoredMessages,
  readStoredChatMaxStoredMessages,
  writeStoredChatMaxStoredMessages,
} from './chatMaxStoredMessagesStorage'

function resolveInitial(): number {
  return readStoredChatMaxStoredMessages()
}

export function ChatMaxStoredMessagesProvider({ children }: { readonly children: ReactNode }) {
  const [chatMaxStoredMessages, setChatMaxStoredMessagesState] = useState(resolveInitial)

  const setChatMaxStoredMessages = useCallback((n: number) => {
    const clamped = clampChatMaxStoredMessages(n)
    setChatMaxStoredMessagesState(clamped)
    writeStoredChatMaxStoredMessages(clamped)
  }, [])

  const value = useMemo(
    () => ({ chatMaxStoredMessages, setChatMaxStoredMessages }),
    [chatMaxStoredMessages, setChatMaxStoredMessages],
  )

  return (
    <ChatMaxStoredMessagesContext.Provider value={value}>{children}</ChatMaxStoredMessagesContext.Provider>
  )
}
