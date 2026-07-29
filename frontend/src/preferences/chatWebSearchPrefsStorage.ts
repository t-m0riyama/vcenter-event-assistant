import { z } from 'zod'

/** WEB 検索条件 prefs を保存する localStorage キー。 */
export const CHAT_WEB_SEARCH_PREFS_STORAGE_KEY = 'vea.chat_web_search_prefs'

export const webSearchScopeSchema = z.enum(['incidents', 'vsphere_ops', 'vmware_ecosystem'])
export const webSearchAggressivenessSchema = z.enum(['conservative', 'balanced', 'aggressive'])

export type WebSearchScope = z.infer<typeof webSearchScopeSchema>
export type WebSearchAggressiveness = z.infer<typeof webSearchAggressivenessSchema>

export type ChatWebSearchPrefs = {
  readonly scope: WebSearchScope
  readonly aggressiveness: WebSearchAggressiveness
}

/** サーバ既定（vmware_ecosystem + balanced）と揃える。 */
export const DEFAULT_CHAT_WEB_SEARCH_PREFS: ChatWebSearchPrefs = {
  scope: 'vmware_ecosystem',
  aggressiveness: 'balanced',
}

const prefsSchema = z.object({
  scope: webSearchScopeSchema,
  aggressiveness: webSearchAggressivenessSchema,
})

/**
 * 保存済みの WEB 検索条件を読む。未設定・不正時は既定値を返す。
 */
export function readStoredChatWebSearchPrefs(): ChatWebSearchPrefs {
  if (typeof localStorage === 'undefined') {
    return { ...DEFAULT_CHAT_WEB_SEARCH_PREFS }
  }
  const raw = localStorage.getItem(CHAT_WEB_SEARCH_PREFS_STORAGE_KEY)
  if (raw === null) {
    return { ...DEFAULT_CHAT_WEB_SEARCH_PREFS }
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(raw) as unknown
  } catch {
    return { ...DEFAULT_CHAT_WEB_SEARCH_PREFS }
  }
  const out = prefsSchema.safeParse(parsed)
  return out.success ? out.data : { ...DEFAULT_CHAT_WEB_SEARCH_PREFS }
}

/**
 * WEB 検索条件を localStorage に保存する。
 */
export function writeStoredChatWebSearchPrefs(prefs: ChatWebSearchPrefs): void {
  if (typeof localStorage === 'undefined') {
    return
  }
  const normalized = prefsSchema.parse(prefs)
  localStorage.setItem(CHAT_WEB_SEARCH_PREFS_STORAGE_KEY, JSON.stringify(normalized))
}
