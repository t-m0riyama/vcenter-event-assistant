import { describe, expect, it, beforeEach } from 'vitest'

import {
  CHAT_WEB_SEARCH_PREFS_STORAGE_KEY,
  DEFAULT_CHAT_WEB_SEARCH_PREFS,
  readStoredChatWebSearchPrefs,
  writeStoredChatWebSearchPrefs,
} from './chatWebSearchPrefsStorage'

describe('chatWebSearchPrefsStorage', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('未設定時は既定値を返す', () => {
    expect(readStoredChatWebSearchPrefs()).toEqual(DEFAULT_CHAT_WEB_SEARCH_PREFS)
  })

  it('書き込んだ値を読める', () => {
    writeStoredChatWebSearchPrefs({ scope: 'incidents', aggressiveness: 'aggressive' })
    expect(readStoredChatWebSearchPrefs()).toEqual({
      scope: 'incidents',
      aggressiveness: 'aggressive',
    })
  })

  it('不正 JSON や未知 enum は既定にフォールバックする', () => {
    localStorage.setItem(CHAT_WEB_SEARCH_PREFS_STORAGE_KEY, '{not-json')
    expect(readStoredChatWebSearchPrefs()).toEqual(DEFAULT_CHAT_WEB_SEARCH_PREFS)

    localStorage.setItem(
      CHAT_WEB_SEARCH_PREFS_STORAGE_KEY,
      JSON.stringify({ scope: 'unknown', aggressiveness: 'balanced' }),
    )
    expect(readStoredChatWebSearchPrefs()).toEqual(DEFAULT_CHAT_WEB_SEARCH_PREFS)
  })
})
