import type { ReactElement } from 'react'

const STROKE = 1.35

/**
 * アシスタント回答コピー用の装飾 SVG（`currentColor`）。
 */
export function ChatCopyAnswerSvg(): ReactElement {
  return (
    <svg
      className="chat-panel__icon-svg"
      viewBox="0 0 16 16"
      width={20}
      height={20}
      fill="none"
      stroke="currentColor"
      strokeWidth={STROKE}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      focusable={false}
    >
      <path d="M5.5 4.5h-2a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2" />
      <rect x="5.5" y="3" width="8" height="10" rx="1" />
      <path d="M8 6.5h3M8 9h2" />
    </svg>
  )
}

/**
 * メッセージ送信用の装飾 SVG（`currentColor`）。
 * 形状は Material「send」系の三角形＋折り返しを 24×24 座標で取り、ボタン内で縮小表示する。
 */
export function ChatSendSvg(): ReactElement {
  return (
    <svg
      className="chat-panel__icon-svg"
      viewBox="0 0 24 24"
      width={20}
      height={20}
      fill="currentColor"
      stroke="none"
      aria-hidden
      focusable={false}
    >
      <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
    </svg>
  )
}

/**
 * プレビュー用の装飾 SVG（`currentColor`）。
 */
export function ChatPreviewSvg(): ReactElement {
  return (
    <svg
      className="chat-panel__icon-svg"
      viewBox="0 0 24 24"
      width={20}
      height={20}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      focusable={false}
    >
      <path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}

