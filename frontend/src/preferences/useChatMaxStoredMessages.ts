import { useContext } from 'react'

import {
  ChatMaxStoredMessagesContext,
  type ChatMaxStoredMessagesContextValue,
} from './chatMaxStoredMessagesContext'

/** ``ChatMaxStoredMessagesProvider`` 配下で最大保持件数設定を取得する。 */
export function useChatMaxStoredMessages(): ChatMaxStoredMessagesContextValue {
  const ctx = useContext(ChatMaxStoredMessagesContext)
  if (!ctx) {
    throw new Error('useChatMaxStoredMessages must be used within ChatMaxStoredMessagesProvider')
  }
  return ctx
}
