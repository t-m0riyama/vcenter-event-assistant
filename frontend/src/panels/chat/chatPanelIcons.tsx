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
 */
export function ChatSendSvg(): ReactElement {
  return (
    <svg
      className="chat-panel__icon-svg"
      viewBox="0 0 16 16"
      width={20}
      height={20}
      fill="currentColor"
      stroke="none"
      aria-hidden
      focusable={false}
    >
      {/* 紙飛行機（送信メタファー） */}
      <path d="M1.5 8 14 2.25 9.75 8 14 13.75 1.5 8z" />
    </svg>
  )
}
