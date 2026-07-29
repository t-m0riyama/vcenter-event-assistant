import { createContext } from 'react'

import type { ChatWebSearchPrefs } from './chatWebSearchPrefsStorage'

/** WEB 検索条件 prefs の Context 値（localStorage と同期）。 */
export type ChatWebSearchPrefsContextValue = {
  readonly prefs: ChatWebSearchPrefs
  readonly setPrefs: (prefs: ChatWebSearchPrefs) => void
}

/** チャット WEB 検索条件 Context。 */
export const ChatWebSearchPrefsContext = createContext<ChatWebSearchPrefsContextValue | null>(null)
