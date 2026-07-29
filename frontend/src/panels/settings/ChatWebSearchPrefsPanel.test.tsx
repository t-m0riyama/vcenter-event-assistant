import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { ChatWebSearchPrefsProvider } from '../../preferences/ChatWebSearchPrefsProvider'
import {
  CHAT_WEB_SEARCH_PREFS_STORAGE_KEY,
  readStoredChatWebSearchPrefs,
} from '../../preferences/chatWebSearchPrefsStorage'
import { ChatWebSearchPrefsPanel } from './ChatWebSearchPrefsPanel'

describe('ChatWebSearchPrefsPanel', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('セレクト変更が localStorage に永続化される', () => {
    render(
      <ChatWebSearchPrefsProvider>
        <ChatWebSearchPrefsPanel />
      </ChatWebSearchPrefsProvider>,
    )

    fireEvent.change(screen.getByLabelText('検索スコープ'), {
      target: { value: 'vsphere_ops' },
    })
    fireEvent.change(screen.getByLabelText('検索の積極度'), {
      target: { value: 'conservative' },
    })

    expect(readStoredChatWebSearchPrefs()).toEqual({
      scope: 'vsphere_ops',
      aggressiveness: 'conservative',
    })
    expect(localStorage.getItem(CHAT_WEB_SEARCH_PREFS_STORAGE_KEY)).toContain('vsphere_ops')
  })
})
