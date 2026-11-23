import { ApiError, apiPost, formatValidationMessage, waitForRetryAfter } from '../api'
import {
  incidentTimelineViewResponseSchema,
  type IncidentTimelineViewRequest,
  type IncidentTimelineViewResponse,
} from './schemas'

/** 混み合い（503）が再試行しても続いたことを示す。 */
export class TimelineBusyError extends Error {
  constructor() {
    super('サーバが混み合っています。しばらく待ってから「更新」を押してください。')
    this.name = 'TimelineBusyError'
  }
}

/** レート制限（429）。`Retry-After` が付かず、すぐ再試行しても同じ結果になるので、自動では再試行しない。 */
export class TimelineRateLimitedError extends Error {
  constructor() {
    super('短時間に操作が多すぎます。少し待ってから「更新」を押してください。')
    this.name = 'TimelineRateLimitedError'
  }
}

/** 再試行を待つ間に条件が変わり、その要求が不要になったことを示す。 */
export class TimelineRequestSupersededError extends Error {
  constructor() {
    super('superseded')
    this.name = 'TimelineRequestSupersededError'
  }
}

/**
 * `POST /api/incident-timeline/view` を呼ぶ。サーバは利用者ごとの同時実行数が 1 で、重なると 503
 * （`Retry-After` 付き）を返す。503 は少し待って 1 回だけ再試行し、それでも失敗したら
 * {@link TimelineBusyError} にする。429 は再試行せず {@link TimelineRateLimitedError} にする。
 * 再試行を待つ間に `signal` が中断されたら、待たずに {@link TimelineRequestSupersededError} で終わる。
 * 422 はサーバの `detail` を載せた {@link ApiError} のまま投げる。
 */
export async function postIncidentTimelineView(
  body: IncidentTimelineViewRequest,
  signal?: AbortSignal,
): Promise<IncidentTimelineViewResponse> {
  const call = async () => {
    try {
      return incidentTimelineViewResponseSchema.parse(await apiPost<unknown>('/api/incident-timeline/view', body))
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 429) throw new TimelineRateLimitedError()
        const message = e.status === 422 ? formatValidationMessage(e.message) : null
        if (message) throw new ApiError(message, e.status, e.errorCode, e.retryAfterSeconds)
      }
      throw e
    }
  }
  try {
    return await call()
  } catch (first) {
    if (!(first instanceof ApiError) || first.status !== 503) throw first
    try {
      await waitForRetryAfter(first.retryAfterSeconds, signal)
    } catch {
      throw new TimelineRequestSupersededError()
    }
    try {
      return await call()
    } catch (second) {
      if (second instanceof ApiError && second.status === 503) throw new TimelineBusyError()
      throw second
    }
  }
}
