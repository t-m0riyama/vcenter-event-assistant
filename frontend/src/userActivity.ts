/**
 * 利用者の操作（クリック・キー入力・ホイール・タッチ）の時刻を記録し、API 要求が利用者の操作に
 * よるものか、画面の定期更新などのバックグラウンドのものかを見分ける。
 *
 * 直近の操作から一定時間たってから出る要求には ``X-VEA-Background: 1`` を付ける。サーバはこの要求で
 * セッションの無操作期限を延ばさないので、画面を開いたまま放置すると無操作タイムアウトでログアウトする。
 *
 * API を呼ばない操作（スクロールや画面内だけの切り替え）も無操作期限に数えるため、操作があったことは
 * 次の要求が出るまで保持し、その要求をバックグラウンド扱いにしない（定期取得の間隔に関係なく必ず伝わる）。
 */

/** 操作からこの時間内に出た要求は、その操作によるものとみなす。 */
export const USER_ACTIVITY_WINDOW_MS = 30_000

export const BACKGROUND_REQUEST_HEADER = 'X-VEA-Background'

const ACTIVITY_EVENTS = ['pointerdown', 'keydown', 'wheel', 'touchstart'] as const

// ページを開いたこと自体も利用者の操作とみなす
let lastActivityAt = Date.now()
/** まだどの要求でもサーバに伝えていない操作があるか。 */
let unreportedActivity = true

export function markUserActivity(now: number = Date.now()): void {
  lastActivityAt = now
  unreportedActivity = true
}

export function isUserIdle(now: number = Date.now()): boolean {
  return !unreportedActivity && now - lastActivityAt > USER_ACTIVITY_WINDOW_MS
}

/**
 * 要求に付けるヘッダ。利用者が操作していなければバックグラウンドの印を付ける。
 * 呼ぶと未報告の操作はこの要求で伝えたものとして消える（要求を送る直前に 1 回だけ呼ぶこと）。
 */
export function activityHeaders(now: number = Date.now()): Record<string, string> {
  const idle = isUserIdle(now)
  unreportedActivity = false
  return idle ? { [BACKGROUND_REQUEST_HEADER]: '1' } : {}
}

if (typeof window !== 'undefined') {
  for (const type of ACTIVITY_EVENTS) {
    window.addEventListener(type, () => markUserActivity(), { capture: true, passive: true })
  }
}
