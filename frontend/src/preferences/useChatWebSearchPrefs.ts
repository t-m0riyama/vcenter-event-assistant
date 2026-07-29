import { useContext } from 'react'

import {
  ChatWebSearchPrefsContext,
  type ChatWebSearchPrefsContextValue,
} from './chatWebSearchPrefsContext'

/** ``ChatWebSearchPrefsProvider`` 配下で WEB 検索条件 prefs を取得する。 */
export function useChatWebSearchPrefs(): ChatWebSearchPrefsContextValue {
  const ctx = useContext(ChatWebSearchPrefsContext)
  if (!ctx) {
    throw new Error('useChatWebSearchPrefs must be used within ChatWebSearchPrefsProvider')
  }
  return ctx
}
