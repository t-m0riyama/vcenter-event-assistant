/** チャットで保持する会話メッセージの最大件数（0〜1000）を保存する localStorage キー。 */
export const CHAT_MAX_STORED_MESSAGES_STORAGE_KEY = 'vea.chat_max_stored_messages.v1'

/** ユーザー設定の最小値（0 は会話を保持しない）。 */
export const CHAT_MAX_STORED_MESSAGES_MIN = 0

/** ユーザー設定の最大値。 */
export const CHAT_MAX_STORED_MESSAGES_MAX = 1000

/**
 * 未設定時の既定（従来の固定上限 200 と同じ）。
 * @see {@link DEFAULT_CHAT_MAX_STORED_MESSAGES} in `./chatPanelStorage`（再エクスポート用）
 */
export const DEFAULT_CHAT_MAX_STORED_MESSAGES = 200

/**
 * チャットに保持する会話メッセージの最大件数を 0〜1000 の整数に収める。
 */
export function clampChatMaxStoredMessages(n: number): number {
  return Math.min(
    CHAT_MAX_STORED_MESSAGES_MAX,
    Math.max(CHAT_MAX_STORED_MESSAGES_MIN, Math.trunc(n)),
  )
}

/**
 * 保存済みの最大件数を読む。未設定・不正時は既定値を返す。
 */
export function readStoredChatMaxStoredMessages(): number {
  if (typeof localStorage === 'undefined') {
    return DEFAULT_CHAT_MAX_STORED_MESSAGES
  }
  const raw = localStorage.getItem(CHAT_MAX_STORED_MESSAGES_STORAGE_KEY)
  if (raw === null) {
    return DEFAULT_CHAT_MAX_STORED_MESSAGES
  }
  const n = Number.parseInt(raw, 10)
  if (Number.isNaN(n)) {
    return DEFAULT_CHAT_MAX_STORED_MESSAGES
  }
  return clampChatMaxStoredMessages(n)
}

/**
 * 最大件数を保存する（クランプ後に文字列で書き込む）。
 */
export function writeStoredChatMaxStoredMessages(n: number): void {
  if (typeof localStorage === 'undefined') {
    return
  }
  const v = clampChatMaxStoredMessages(n)
  localStorage.setItem(CHAT_MAX_STORED_MESSAGES_STORAGE_KEY, String(v))
}
