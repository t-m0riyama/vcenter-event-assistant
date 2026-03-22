import { useContext } from 'react'
import {
  AutoRefreshPreferencesContext,
  type AutoRefreshPreferencesContextValue,
} from './autoRefreshPreferencesContext'

/**
 * 自動更新の有効／無効と間隔（分）を取得する。`AutoRefreshPreferencesProvider` 内で使う。
 */
export function useAutoRefreshPreferences(): AutoRefreshPreferencesContextValue {
  const ctx = useContext(AutoRefreshPreferencesContext)
  if (!ctx) {
    throw new Error(
      'useAutoRefreshPreferences must be used within AutoRefreshPreferencesProvider',
    )
  }
  return ctx
}
