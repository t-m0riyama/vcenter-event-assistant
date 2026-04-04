import type { ReactElement, ReactNode } from 'react'

const STROKE = 1.25

type TabButtonSvgIconProps = {
  readonly children: ReactNode
}

/**
 * メインタブ・設定サブタブ共通の装飾用 SVG（16×16・`currentColor`）。
 */
export function TabButtonSvgIcon({ children }: TabButtonSvgIconProps): ReactElement {
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
