/**
 * 利用者の操作（クリック・キー入力・ホイール・タッチ）の時刻を記録し、API 要求が利用者の操作に
 * よるものか、画面の定期更新などのバックグラウンドのものかを見分ける。
 *
 * 直近の操作から一定時間たってから出る要求には ``X-VEA-Background: 1`` を付ける。サーバはこの要求で
 * セッションの無操作期限を延ばさないので、画面を開いたまま放置すると無操作タイムアウトでログアウトする。
 */

/** 操作からこの時間内に出た要求は、その操作によるものとみなす。 */
export const USER_ACTIVITY_WINDOW_MS = 30_000

export const BACKGROUND_REQUEST_HEADER = 'X-VEA-Background'

const ACTIVITY_EVENTS = ['pointerdown', 'keydown', 'wheel', 'touchstart'] as const

// ページを開いたこと自体も利用者の操作とみなす
let lastActivityAt = Date.now()

export function markUserActivity(now: number = Date.now()): void {
  lastActivityAt = now
}

export function isUserIdle(now: number = Date.now()): boolean {
  return now - lastActivityAt > USER_ACTIVITY_WINDOW_MS
}

/** 要求に付けるヘッダ。利用者が操作していなければバックグラウンドの印を付ける。 */
export function activityHeaders(now: number = Date.now()): Record<string, string> {
  return isUserIdle(now) ? { [BACKGROUND_REQUEST_HEADER]: '1' } : {}
}

if (typeof window !== 'undefined') {
  for (const type of ACTIVITY_EVENTS) {
    window.addEventListener(type, () => markUserActivity(), { capture: true, passive: true })
  }
}
