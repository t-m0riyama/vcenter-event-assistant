import { ApiError, apiPost } from '../api'
import {
  incidentTimelineViewResponseSchema,
  type IncidentTimelineViewRequest,
  type IncidentTimelineViewResponse,
} from './schemas'

/** 混み合い（503 / 429）が再試行しても続いたことを示す。 */
export class TimelineBusyError extends Error {
  constructor() {
    super('サーバが混み合っています。しばらく待ってから「更新」を押してください。')
    this.name = 'TimelineBusyError'
  }
}

/** 再試行を待つ間に条件が変わり、その要求が不要になったことを示す。 */
export class TimelineRequestSupersededError extends Error {
  constructor() {
    super('superseded')
    this.name = 'TimelineRequestSupersededError'
  }
}

/** `Retry-After` が無いときの待ち時間（ミリ秒）。 */
export const TIMELINE_RETRY_DEFAULT_WAIT_MS = 3000
/** `Retry-After` が大きくても待つ上限（ミリ秒）。 */
export const TIMELINE_RETRY_MAX_WAIT_MS = 10_000

const BUSY_STATUSES = new Set([503, 429])

function isBusy(e: unknown): e is ApiError {
  return e instanceof ApiError && BUSY_STATUSES.has(e.status)
}

function retryWaitMs(e: ApiError): number {
  const ms = e.retryAfterSeconds === null ? TIMELINE_RETRY_DEFAULT_WAIT_MS : e.retryAfterSeconds * 1000
  return Math.min(ms, TIMELINE_RETRY_MAX_WAIT_MS)
}

/**
 * `POST /api/incident-timeline/view` を呼ぶ。サーバは利用者ごとの同時実行数が 1 で、重なると 503
 * （`Retry-After` 付き）を返す。503 と 429 は少し待って 1 回だけ再試行し、それでも失敗したら
 * {@link TimelineBusyError} にする。再試行を待つ間に不要になったら `isSuperseded` で取りやめる。
 * 422 などはサーバの `detail` を載せた {@link ApiError} のまま投げる。
 */
export async function postIncidentTimelineView(
  body: IncidentTimelineViewRequest,
  isSuperseded: () => boolean = () => false,
): Promise<IncidentTimelineViewResponse> {
  const call = async () =>
    incidentTimelineViewResponseSchema.parse(await apiPost<unknown>('/api/incident-timeline/view', body))
  try {
    return await call()
  } catch (first) {
    if (!isBusy(first)) throw first
    await new Promise((resolve) => setTimeout(resolve, retryWaitMs(first)))
    if (isSuperseded()) throw new TimelineRequestSupersededError()
    try {
      return await call()
    } catch (second) {
      if (isBusy(second)) throw new TimelineBusyError()
      throw second
    }
  }
}
