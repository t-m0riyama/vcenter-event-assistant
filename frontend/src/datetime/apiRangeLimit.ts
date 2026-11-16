import { parseApiUtcInstantMs } from './formatIsoInTimeZone'

/** API（タイムライン・チャット）が受け付ける期間の最大の長さ（ミリ秒）。 */
export const API_RANGE_MAX_SPAN_MS = 90 * 86_400_000

/** API が受け付けない期間（逆順・同じ秒・90 日超）の理由。問題なければ null。 */
export function validateApiRange(range: { readonly from: string; readonly to: string }): string | null {
  const from = parseApiUtcInstantMs(range.from)
  const to = parseApiUtcInstantMs(range.to)
  if (!Number.isFinite(from) || !Number.isFinite(to)) return '期間の開始と終了を指定してください。'
  if (Math.floor(from / 1000) >= Math.floor(to / 1000)) return '開始は終了より前の時刻にしてください。'
  if (to - from > API_RANGE_MAX_SPAN_MS) return '期間は 90 日以内にしてください。'
  return null
}
