import { createContext } from 'react'

/** 非設定タブの自動更新設定の Context 値。 */
export type AutoRefreshPreferencesContextValue = {
  autoRefreshEnabled: boolean
  setAutoRefreshEnabled: (enabled: boolean) => void
  autoRefreshIntervalMinutes: number
  setAutoRefreshIntervalMinutes: (minutes: number) => void
}

export const AutoRefreshPreferencesContext =
  createContext<AutoRefreshPreferencesContextValue | null>(null)
