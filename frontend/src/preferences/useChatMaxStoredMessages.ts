import { useContext } from 'react'

import {
  ChatMaxStoredMessagesContext,
  type ChatMaxStoredMessagesContextValue,
} from './chatMaxStoredMessagesContext'

export function useChatMaxStoredMessages(): ChatMaxStoredMessagesContextValue {
  const ctx = useContext(ChatMaxStoredMessagesContext)
  if (!ctx) {
    throw new Error('useChatMaxStoredMessages must be used within ChatMaxStoredMessagesProvider')
  }
  return ctx
}
