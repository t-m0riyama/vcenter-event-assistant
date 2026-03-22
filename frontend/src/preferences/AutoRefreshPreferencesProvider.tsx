/**
 * 概要・イベント・グラフの自動更新設定（有効／無効・間隔）を Context と localStorage で共有する。
 */
import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { AutoRefreshPreferencesContext } from './autoRefreshPreferencesContext'
import {
  clampAutoRefreshIntervalMinutes,
  readStoredAutoRefreshEnabled,
  readStoredAutoRefreshIntervalMinutes,
  writeStoredAutoRefreshEnabled,
  writeStoredAutoRefreshIntervalMinutes,
} from './autoRefreshPreferencesStorage'

function resolveInitialEnabled(): boolean {
  return readStoredAutoRefreshEnabled()
}

function resolveInitialIntervalMinutes(): number {
  return readStoredAutoRefreshIntervalMinutes()
}

/** 自動更新設定を子ツリーへ提供する。 */
export function AutoRefreshPreferencesProvider({ children }: { children: ReactNode }) {
  const [autoRefreshEnabled, setAutoRefreshEnabledState] = useState(resolveInitialEnabled)
  const [autoRefreshIntervalMinutes, setAutoRefreshIntervalMinutesState] = useState(
    resolveInitialIntervalMinutes,
  )

  const setAutoRefreshEnabled = useCallback((enabled: boolean) => {
    setAutoRefreshEnabledState(enabled)
    writeStoredAutoRefreshEnabled(enabled)
  }, [])

  const setAutoRefreshIntervalMinutes = useCallback((minutes: number) => {
    const v = clampAutoRefreshIntervalMinutes(minutes)
    setAutoRefreshIntervalMinutesState(v)
    writeStoredAutoRefreshIntervalMinutes(v)
  }, [])

  const value = useMemo(
    () => ({
      autoRefreshEnabled,
      setAutoRefreshEnabled,
      autoRefreshIntervalMinutes,
      setAutoRefreshIntervalMinutes,
    }),
    [autoRefreshEnabled, setAutoRefreshEnabled, autoRefreshIntervalMinutes, setAutoRefreshIntervalMinutes],
  )

  return (
    <AutoRefreshPreferencesContext.Provider value={value}>
      {children}
    </AutoRefreshPreferencesContext.Provider>
  )
}
