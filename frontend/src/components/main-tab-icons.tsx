import type { ReactElement } from 'react'

/**
 * アプリ上部メインタブ（概要〜設定）の識別子。タブ用インライン SVG と `App` のタブ状態で共有する。
 */
export type MainTabId = 'summary' | 'events' | 'metrics' | 'digests' | 'chat' | 'settings'

const STROKE = 1.25

type SvgIconProps = {
  readonly children: React.ReactNode
}

function TabSvgIcon({ children }: SvgIconProps): ReactElement {
  return (
    <svg
      className="tab-button__icon"
      viewBox="0 0 16 16"
      width={16}
      height={16}
      fill="none"
      stroke="currentColor"
      strokeWidth={STROKE}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      focusable={false}
    >
      {children}
    </svg>
  )
}

/**
 * メインタブ用の装飾アイコン（`currentColor` でテーマに追従。スクリーンリーダーからは隠す）。
 */
export function MainTabIcon({ tabId }: { readonly tabId: MainTabId }): ReactElement {
  switch (tabId) {
    case 'summary':
      return (
        <TabSvgIcon>
          <rect x="2" y="2" width="12" height="3" rx="0.75" />
          <rect x="2" y="7" width="5" height="7" rx="0.75" />
          <rect x="9" y="7" width="5" height="7" rx="0.75" />
        </TabSvgIcon>
      )
    case 'events':
      return (
        <TabSvgIcon>
          <circle cx="3.5" cy="4" r="1" />
          <circle cx="3.5" cy="8" r="1" />
          <circle cx="3.5" cy="12" r="1" />
          <line x1="6.5" y1="4" x2="13" y2="4" />
          <line x1="6.5" y1="8" x2="13" y2="8" />
          <line x1="6.5" y1="12" x2="13" y2="12" />
        </TabSvgIcon>
      )
    case 'metrics':
      return (
        <TabSvgIcon>
          <polyline points="2,12 5.5,8 9,10 14,4" />
        </TabSvgIcon>
      )
    case 'digests':
      return (
        <TabSvgIcon>
          <rect x="3" y="2" width="10" height="12" rx="1.25" />
          <line x1="5.5" y1="5.5" x2="10.5" y2="5.5" />
          <line x1="5.5" y1="8" x2="10.5" y2="8" />
          <line x1="5.5" y1="10.5" x2="9" y2="10.5" />
        </TabSvgIcon>
      )
    case 'chat':
      return (
        <TabSvgIcon>
          <path d="M3.5 3.5h9a1.5 1.5 0 0 1 1.5 1.5v4.5a1.5 1.5 0 0 1-1.5 1.5H9.2L6.5 14v-2.5H3.5A1.5 1.5 0 0 1 2 9.5V5A1.5 1.5 0 0 1 3.5 3.5z" />
        </TabSvgIcon>
      )
    case 'settings':
      /* 外周が凹凸する 6 歯の歯車輪郭（計画の「円周に短い歯」）＋中心穴 */
      return (
        <TabSvgIcon>
          <path d="M8 2.2 10.1 4.4 13 5.1 12.2 8 13 10.9 10.1 11.6 8 13.8 5.9 11.6 3 10.9 3.8 8 3 5.1 5.9 4.4z" />
          <circle cx="8" cy="8" r="2.25" />
        </TabSvgIcon>
      )
    default: {
      const _exhaustive: never = tabId
      return _exhaustive
    }
  }
}
