import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  CHAT_MAX_STORED_MESSAGES_STORAGE_KEY,
  clampChatMaxStoredMessages,
  DEFAULT_CHAT_MAX_STORED_MESSAGES,
  readStoredChatMaxStoredMessages,
  writeStoredChatMaxStoredMessages,
} from './chatMaxStoredMessagesStorage'

describe('clampChatMaxStoredMessages', () => {
  it('0〜1000 に収め、小数は切り捨てる', () => {
    expect(clampChatMaxStoredMessages(-1)).toBe(0)
    expect(clampChatMaxStoredMessages(1001)).toBe(1000)
    expect(clampChatMaxStoredMessages(42.7)).toBe(42)
    expect(clampChatMaxStoredMessages(0)).toBe(0)
    expect(clampChatMaxStoredMessages(1000)).toBe(1000)
  })
})

describe('readStoredChatMaxStoredMessages / writeStoredChatMaxStoredMessages', () => {
  afterEach(() => {
    localStorage.removeItem(CHAT_MAX_STORED_MESSAGES_STORAGE_KEY)
  })

  it('未設定なら既定 200', () => {
    expect(readStoredChatMaxStoredMessages()).toBe(DEFAULT_CHAT_MAX_STORED_MESSAGES)
  })

  it('write 後に read で同一値', () => {
    writeStoredChatMaxStoredMessages(500)
    expect(readStoredChatMaxStoredMessages()).toBe(500)
    expect(localStorage.getItem(CHAT_MAX_STORED_MESSAGES_STORAGE_KEY)).toBe('500')
  })

  it('範囲外はクランプして保存する', () => {
    writeStoredChatMaxStoredMessages(9999)
    expect(readStoredChatMaxStoredMessages()).toBe(1000)
  })

  it('localStorage が無い環境では read は既定・write は no-op', () => {
    vi.stubGlobal('localStorage', undefined)
    expect(readStoredChatMaxStoredMessages()).toBe(DEFAULT_CHAT_MAX_STORED_MESSAGES)
    expect(() => writeStoredChatMaxStoredMessages(100)).not.toThrow()
    vi.unstubAllGlobals()
  })
})
