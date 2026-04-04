import type { ReactElement } from 'react'

import { TabButtonSvgIcon } from './tab-svg-icon'

/**
 * 設定タブ内サブナビの識別子。`App` の `settingsSubTab` と共有する。
 */
export type SettingsSubTabId = 'general' | 'vcenters' | 'score_rules' | 'event_type_guides'

/**
 * 設定サブタブ用の装飾アイコン（`currentColor`・スクリーンリーダーからは隠す）。
 */
export function SettingsSubTabIcon({ tabId }: { readonly tabId: SettingsSubTabId }): ReactElement {
  switch (tabId) {
    case 'general':
      return (
        <TabButtonSvgIcon>
          <line x1="3" y1="4.5" x2="13" y2="4.5" />
          <circle cx="9" cy="4.5" r="0.9" />
          <line x1="3" y1="8" x2="13" y2="8" />
          <circle cx="6" cy="8" r="0.9" />
          <line x1="3" y1="11.5" x2="13" y2="11.5" />
          <circle cx="11" cy="11.5" r="0.9" />
        </TabButtonSvgIcon>
      )
    case 'vcenters':
      return (
        <TabButtonSvgIcon>
          <rect x="3" y="2.5" width="10" height="2.8" rx="0.5" />
          <rect x="3" y="6.1" width="10" height="2.8" rx="0.5" />
          <rect x="3" y="9.7" width="10" height="2.8" rx="0.5" />
          <line x1="4" y1="4.3" x2="12" y2="4.3" />
          <line x1="4" y1="7.9" x2="12" y2="7.9" />
          <line x1="4" y1="11.5" x2="12" y2="11.5" />
        </TabButtonSvgIcon>
      )
    case 'score_rules':
      return (
        <TabButtonSvgIcon>
          <line x1="5.5" y1="3" x2="5.5" y2="13" />
          <line x1="8" y1="3" x2="8" y2="13" />
          <line x1="3" y1="6" x2="13" y2="6" />
          <line x1="3" y1="10" x2="13" y2="10" />
        </TabButtonSvgIcon>
      )
    case 'event_type_guides':
      return (
        <TabButtonSvgIcon>
          <line x1="8" y1="3.5" x2="8" y2="12.5" />
          <rect x="2.5" y="3.5" width="5" height="9" rx="0.75" />
          <rect x="8.5" y="3.5" width="5" height="9" rx="0.75" />
        </TabButtonSvgIcon>
      )
    default: {
      const _exhaustive: never = tabId
      return _exhaustive
    }
  }
}
