import { ApiError, apiPost } from '../api'
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

/** `Retry-After` が無いときの待ち時間（ミリ秒）。 */
export const TIMELINE_RETRY_DEFAULT_WAIT_MS = 3000
/** `Retry-After` が大きくても待つ上限（ミリ秒）。 */
export const TIMELINE_RETRY_MAX_WAIT_MS = 10_000

function retryWaitMs(e: ApiError): number {
  const ms = e.retryAfterSeconds === null ? TIMELINE_RETRY_DEFAULT_WAIT_MS : e.retryAfterSeconds * 1000
  return Math.min(ms, TIMELINE_RETRY_MAX_WAIT_MS)
}

/** 待つ。`signal` が中断されたら、待たずに {@link TimelineRequestSupersededError} で終わる。 */
function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new TimelineRequestSupersededError())
      return
    }
    const onAbort = () => {
      clearTimeout(timer)
      reject(new TimelineRequestSupersededError())
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

/**
 * 422 の検証エラーは `detail` が `[{loc, msg}]` の配列で、共通の `apiPost` は本文の文字列をそのまま
 * message にする。タイムラインでは「項目: 理由」の形に整える（文字列の `detail` は共通側が展開済み）。
 */
function formatValidationMessage(e: ApiError): ApiError {
  if (e.status !== 422) return e
  try {
    const body: unknown = JSON.parse(e.message)
    const detail = body && typeof body === 'object' && 'detail' in body ? body.detail : null
    if (!Array.isArray(detail)) return e
    const lines = detail
      .map((entry: unknown) => {
        if (!entry || typeof entry !== 'object' || !('msg' in entry) || typeof entry.msg !== 'string') return null
        const loc =
          'loc' in entry && Array.isArray(entry.loc)
            ? entry.loc.filter((part: unknown) => part !== 'body').join('.')
            : ''
        return loc ? `${loc}: ${entry.msg}` : entry.msg
      })
      .filter((line): line is string => line !== null)
    return lines.length > 0 ? new ApiError(lines.join(' / '), e.status, e.errorCode, e.retryAfterSeconds) : e
  } catch {
    return e
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
        throw formatValidationMessage(e)
      }
      throw e
    }
  }
  try {
    return await call()
  } catch (first) {
    if (!(first instanceof ApiError) || first.status !== 503) throw first
    await sleep(retryWaitMs(first), signal)
    try {
      return await call()
    } catch (second) {
      if (second instanceof ApiError && second.status === 503) throw new TimelineBusyError()
      throw second
    }
  }
}
