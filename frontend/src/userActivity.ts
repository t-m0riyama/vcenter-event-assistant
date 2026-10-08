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

/**
 * 操作をサーバに伝えた最後の要求からこの時間がたっていたら、API を呼ばない操作でも報告の要求を送る。
 * 既定値。実際にはサーバが返す更新間隔（無操作タイムアウトが短いと縮む）を ``setActivityReporter`` で渡す。
 */
export const ACTIVITY_REPORT_INTERVAL_MS = 60_000

/** 操作が続いているあいだに報告を何度も送らないよう、最後の操作からこの時間待って送る。 */
export const ACTIVITY_REPORT_DEBOUNCE_MS = 2_000

export const BACKGROUND_REQUEST_HEADER = 'X-VEA-Background'

const ACTIVITY_EVENTS = ['pointerdown', 'keydown', 'wheel', 'touchstart'] as const

// ページを開いたこと自体も利用者の操作とみなす
let lastActivityAt = Date.now()
/** まだどの要求でもサーバに伝えていない操作があるか。 */
let unreportedActivity = true
/** 操作をサーバに伝えた（バックグラウンドでない）最後の要求の時刻。 */
let lastReportedAt = 0
let reporter: (() => Promise<unknown>) | null = null
let reportIntervalMs = ACTIVITY_REPORT_INTERVAL_MS
let reportTimer: ReturnType<typeof setTimeout> | null = null

export function markUserActivity(now: number = Date.now()): void {
  lastActivityAt = now
  unreportedActivity = true
  scheduleReport(now)
}

/**
 * API を呼ばない操作（スクロールなど）でも、サーバの無操作期限が切れる前に伝わるよう報告の要求を送る。
 * 操作が続く間は最後の操作から少し待ち、前回の報告から更新間隔がたっていなければその時点まで遅らせる
 * （間隔より短い報告はサーバが最終利用時刻を更新しないため）。
 */
function scheduleReport(now: number): void {
  if (!reporter) return
  const dueAt = Math.max(now + ACTIVITY_REPORT_DEBOUNCE_MS, lastReportedAt + reportIntervalMs)
  if (reportTimer !== null) clearTimeout(reportTimer)
  reportTimer = setTimeout(() => {
    reportTimer = null
    // 待っている間に別の要求で伝わっていれば送らない
    if (!unreportedActivity || !reporter) return
    const previousReportedAt = lastReportedAt
    void reporter().catch(() => {
      // 失敗したら伝わっていないので、未報告に戻す（次の操作や要求で改めて伝える）
      unreportedActivity = true
      lastReportedAt = previousReportedAt
    })
  }, dueAt - now)
}

/**
 * 操作の報告に使う要求を登録する（ログイン中だけ）。戻り値で登録を解除する。
 * 要求は ``activityHeaders()`` を付けて送ること。
 */
export function setActivityReporter(
  report: () => Promise<unknown>,
  intervalMs: number = ACTIVITY_REPORT_INTERVAL_MS,
): () => void {
  reporter = report
  reportIntervalMs = intervalMs
  return () => {
    if (reporter === report) reporter = null
    if (reportTimer !== null) {
      clearTimeout(reportTimer)
      reportTimer = null
    }
  }
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
  if (!idle) lastReportedAt = now
  return idle ? { [BACKGROUND_REQUEST_HEADER]: '1' } : {}
}

if (typeof window !== 'undefined') {
  for (const type of ACTIVITY_EVENTS) {
    window.addEventListener(type, () => markUserActivity(), { capture: true, passive: true })
  }
}
