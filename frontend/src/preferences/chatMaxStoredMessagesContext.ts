import { createContext } from 'react'

/** チャットに保持する会話メッセージの最大件数（0〜1000）の Context 値。 */
export type ChatMaxStoredMessagesContextValue = {
  chatMaxStoredMessages: number
  setChatMaxStoredMessages: (n: number) => void
}

export const ChatMaxStoredMessagesContext = createContext<ChatMaxStoredMessagesContextValue | null>(
  null,
)
