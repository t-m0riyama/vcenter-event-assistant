import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY } from '../../preferences/chatCustomSamplePromptsStorage'
import { ChatCustomSamplePromptsProvider } from '../../preferences/ChatCustomSamplePromptsProvider'
import { ChatCustomSamplePromptsPanel } from './ChatCustomSamplePromptsPanel'

describe('ChatCustomSamplePromptsPanel', () => {
  afterEach(() => {
    localStorage.removeItem(CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY)
  })

  it('サンプルを追加すると localStorage に保存される', async () => {
    render(
      <ChatCustomSamplePromptsProvider>
        <ChatCustomSamplePromptsPanel />
      </ChatCustomSamplePromptsProvider>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'サンプルを追加' }))

    await waitFor(() => {
      const raw = localStorage.getItem(CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY)
      expect(raw).toBeTruthy()
      const parsed = JSON.parse(String(raw)) as { label: string }[]
      expect(parsed.length).toBe(1)
      expect(parsed[0].label).toBe('新しいサンプル')
    })
  })
})
