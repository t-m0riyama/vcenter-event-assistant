/**
 * WEB 検索のスコープ・積極度を localStorage と同期して提供する。
 */
import { useCallback, useMemo, useState, type ReactNode } from 'react'

import { ChatWebSearchPrefsContext } from './chatWebSearchPrefsContext'
import {
  readStoredChatWebSearchPrefs,
  writeStoredChatWebSearchPrefs,
  type ChatWebSearchPrefs,
} from './chatWebSearchPrefsStorage'

/** チャット WEB 検索条件を Context と localStorage で提供する Provider。 */
export function ChatWebSearchPrefsProvider({ children }: { readonly children: ReactNode }) {
  const [prefs, setPrefsState] = useState(readStoredChatWebSearchPrefs)

  const setPrefs = useCallback((next: ChatWebSearchPrefs) => {
    writeStoredChatWebSearchPrefs(next)
    setPrefsState(next)
  }, [])

  const value = useMemo(() => ({ prefs, setPrefs }), [prefs, setPrefs])

  return (
    <ChatWebSearchPrefsContext.Provider value={value}>{children}</ChatWebSearchPrefsContext.Provider>
  )
}
