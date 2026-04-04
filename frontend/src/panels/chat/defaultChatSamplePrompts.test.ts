import { describe, expect, it } from 'vitest'

import {
  getInitialChatSamplePromptsSnapshot,
  INITIAL_CHAT_SAMPLE_PROMPTS,
} from './defaultChatSamplePrompts'

describe('defaultChatSamplePrompts', () => {
  it('getInitialChatSamplePromptsSnapshot は INITIAL と等価な新しい配列・オブジェクト', () => {
    const snap = getInitialChatSamplePromptsSnapshot()
    expect(snap).toEqual([...INITIAL_CHAT_SAMPLE_PROMPTS])
    expect(snap).not.toBe(INITIAL_CHAT_SAMPLE_PROMPTS)
    expect(snap[0]).not.toBe(INITIAL_CHAT_SAMPLE_PROMPTS[0])
  })
})
