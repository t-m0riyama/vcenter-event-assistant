import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { INITIAL_CHAT_SAMPLE_PROMPTS } from '../chat/defaultChatSamplePrompts'
import {
  CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY,
  CHAT_SAMPLE_PROMPTS_STORAGE_KEY,
} from '../../preferences/chatSamplePromptsStorage'
import { ChatCustomSamplePromptsProvider } from '../../preferences/ChatCustomSamplePromptsProvider'
import { ChatCustomSamplePromptsPanel } from './ChatCustomSamplePromptsPanel'

describe('ChatCustomSamplePromptsPanel', () => {
  afterEach(() => {
    localStorage.removeItem(CHAT_SAMPLE_PROMPTS_STORAGE_KEY)
    localStorage.removeItem(CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY)
  })

  it('サンプルを追加すると localStorage に保存され、一覧に行が増える', async () => {
    render(
      <ChatCustomSamplePromptsProvider>
        <ChatCustomSamplePromptsPanel onError={vi.fn()} />
      </ChatCustomSamplePromptsProvider>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'サンプルを追加' }))

    await waitFor(() => {
      const raw = localStorage.getItem(CHAT_SAMPLE_PROMPTS_STORAGE_KEY)
      expect(raw).toBeTruthy()
      const parsed = JSON.parse(String(raw)) as { label: string }[]
      expect(parsed.length).toBe(INITIAL_CHAT_SAMPLE_PROMPTS.length + 1)
      expect(parsed.some((r) => r.label === '新しいサンプル')).toBe(true)
    })
  })

  it('既定 id の行を削除できる', async () => {
    const targetId = INITIAL_CHAT_SAMPLE_PROMPTS[0].id
    localStorage.setItem(CHAT_SAMPLE_PROMPTS_STORAGE_KEY, JSON.stringify([...INITIAL_CHAT_SAMPLE_PROMPTS]))

    render(
      <ChatCustomSamplePromptsProvider>
        <ChatCustomSamplePromptsPanel onError={vi.fn()} />
      </ChatCustomSamplePromptsProvider>,
    )

    const labelInput = screen.getByLabelText(`サンプル ${targetId} の表示ラベル`)
    const row = labelInput.closest('li')
    expect(row).toBeTruthy()
    fireEvent.click(within(row as HTMLElement).getByRole('button', { name: '削除' }))

    await waitFor(() => {
      const raw = localStorage.getItem(CHAT_SAMPLE_PROMPTS_STORAGE_KEY)
      const parsed = JSON.parse(String(raw)) as { id: string }[]
      expect(parsed.some((r) => r.id === targetId)).toBe(false)
    })
  })
})
