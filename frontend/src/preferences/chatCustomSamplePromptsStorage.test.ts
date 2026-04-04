import { afterEach, describe, expect, it } from 'vitest'

import {
  CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY,
  readStoredChatCustomSamplePrompts,
  writeStoredChatCustomSamplePrompts,
} from './chatCustomSamplePromptsStorage'

describe('chatCustomSamplePromptsStorage', () => {
  afterEach(() => {
    localStorage.removeItem(CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY)
  })

  it('未設定時は空配列を返す', () => {
    expect(readStoredChatCustomSamplePrompts()).toEqual([])
  })

  it('正しい JSON を読み書きできる', () => {
    const rows = [
      { id: 'c1', label: 'カスタム1', text: '本文1' },
      { id: 'c2', label: 'カスタム2', text: '本文2' },
    ]
    writeStoredChatCustomSamplePrompts(rows)
    expect(readStoredChatCustomSamplePrompts()).toEqual(rows)
  })

  it('不正 JSON のときは空配列を返す', () => {
    localStorage.setItem(CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY, '{not json')
    expect(readStoredChatCustomSamplePrompts()).toEqual([])
  })

  it('Zod で弾かれる要素は読み込まない', () => {
    localStorage.setItem(
      CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY,
      JSON.stringify([{ id: '', label: 'x', text: 'y' }]),
    )
    expect(readStoredChatCustomSamplePrompts()).toEqual([])
  })
})
