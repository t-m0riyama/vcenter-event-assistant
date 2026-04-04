import { useContext } from 'react'

import {
  ChatCustomSamplePromptsContext,
  type ChatCustomSamplePromptsContextValue,
} from './chatCustomSamplePromptsContext'

export function useChatCustomSamplePrompts(): ChatCustomSamplePromptsContextValue {
  const ctx = useContext(ChatCustomSamplePromptsContext)
  if (!ctx) {
    throw new Error('useChatCustomSamplePrompts must be used within ChatCustomSamplePromptsProvider')
  }
  return ctx
}
