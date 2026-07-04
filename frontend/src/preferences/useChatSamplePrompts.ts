import { useContext } from 'react'

import { ChatSamplePromptsContext, type ChatSamplePromptsContextValue } from './chatSamplePromptsContext'

/** ``ChatSamplePromptsProvider`` 配下でサンプルプロンプト一覧を取得する。 */
export function useChatSamplePrompts(): ChatSamplePromptsContextValue {
  const ctx = useContext(ChatSamplePromptsContext)
  if (!ctx) {
    throw new Error('useChatSamplePrompts must be used within ChatSamplePromptsProvider')
  }
  return ctx
}
