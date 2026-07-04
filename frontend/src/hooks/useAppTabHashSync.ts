import { useCallback, useEffect, useState } from 'react'

import type { MainTabId } from '../components/main-tab-icons'
import type { SettingsSubTabId } from '../components/settings-subtab-icons'
import { parseAppHash, replaceAppHash } from '../routing/appHashRouting'

/**
 * メインタブと設定サブタブを URL ハッシュ（`#/events` 等）と双方向同期する。
 */
export function useAppTabHashSync() {
  const [tab, setTabState] = useState<MainTabId>(() => parseAppHash(window.location.hash).tab)
  const [settingsSubTab, setSettingsSubTabState] = useState<SettingsSubTabId>(
    () => parseAppHash(window.location.hash).settingsSubTab,
  )

  useEffect(() => {
    if (!window.location.hash) {
      replaceAppHash(tab, settingsSubTab)
    }
    // 初回のみ空ハッシュを正規化する
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const syncFromHash = () => {
      const parsed = parseAppHash(window.location.hash)
      setTabState(parsed.tab)
      setSettingsSubTabState(parsed.settingsSubTab)
    }
    window.addEventListener('hashchange', syncFromHash)
    return () => window.removeEventListener('hashchange', syncFromHash)
  }, [])

  const setTab = useCallback((next: MainTabId) => {
    setTabState(next)
    setSettingsSubTabState((sub) => {
      replaceAppHash(next, next === 'settings' ? sub : 'general')
      return sub
    })
  }, [])

  const setSettingsSubTab = useCallback((next: SettingsSubTabId) => {
    setSettingsSubTabState(next)
    replaceAppHash('settings', next)
  }, [])

  return { tab, setTab, settingsSubTab, setSettingsSubTab }
}
