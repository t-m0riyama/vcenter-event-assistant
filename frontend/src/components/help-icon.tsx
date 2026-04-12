import type { ReactElement } from 'react'

/**
 * 簡易ヘルプ用の装飾アイコン（?マーク）。
 */
export function HelpIcon(): ReactElement {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className="tab-button__icon"
    >
      <circle cx="8" cy="8" r="7" />
      <path d="M7.1 6.5A1.5 1.5 0 1 1 9 8.1c-.5.3-.9.8-.9 1.4" />
      <line x1="8" y1="12" x2="8.01" y2="12" />
    </svg>
  )
}
