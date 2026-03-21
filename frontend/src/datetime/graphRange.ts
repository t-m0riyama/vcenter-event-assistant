import {
  isValidUtcRangeOrder,
  zonedLocalDateTimeToUtcIso,
} from './zonedLocalDateTime'
import {
  zonedRangePartsToCombinedInputs,
  type ZonedRangeParts,
} from './zonedRangeParts'

export type EventRangeResolve =
  | { ok: true; from?: string; to?: string }
  | { ok: false; message: string }

/**
 * Maps optional wall-clock range inputs (display time zone) to API `from` / `to` UTC ISO strings.
 */
export function resolveEventApiRange(
  rangeFromInput: string,
  rangeToInput: string,
  timeZone: string,
): EventRangeResolve {
  const rf = rangeFromInput.trim()
  const rt = rangeToInput.trim()
  if (!rf && !rt) return { ok: true }
  let fromUtc: string | undefined
  let toUtc: string | undefined
  if (rf) {
    const iso = zonedLocalDateTimeToUtcIso(rf, timeZone)
    if (!iso) {
      return {
        ok: false,
        message:
          '開始の日付・時刻が解釈できないか、この時刻は存在しません（例: サマータイムの欠落時刻）。日付と時刻を確認してください。',
      }
    }
    fromUtc = iso
  }
  if (rt) {
    const iso = zonedLocalDateTimeToUtcIso(rt, timeZone)
    if (!iso) {
      return {
        ok: false,
        message:
          '終了の日付・時刻が解釈できないか、この時刻は存在しません（例: サマータイムの欠落時刻）。日付と時刻を確認してください。',
      }
    }
    toUtc = iso
  }
  if (fromUtc && toUtc && !isValidUtcRangeOrder(fromUtc, toUtc)) {
    return { ok: false, message: '開始は終了より前の時刻にしてください。' }
  }
  return { ok: true, from: fromUtc, to: toUtc }
}

export type MetricsGraphRangeResolve =
  | { mode: 'none' }
  | { mode: 'range'; from: string; to: string }
  | { mode: 'invalid'; message: string }

/**
 * Graph tab: either both start/end are empty (no time filter), or both must be valid (same rules as events).
 * One-sided input is rejected so `GET /api/events/rate-series` can use the same bounds as metrics when a range is set.
 */
export function resolveMetricsGraphRange(
  rangeFromInput: string,
  rangeToInput: string,
  timeZone: string,
): MetricsGraphRangeResolve {
  const rf = rangeFromInput.trim()
  const rt = rangeToInput.trim()
  if (!rf && !rt) return { mode: 'none' }
  if (!rf || !rt) {
    return {
      mode: 'invalid',
      message:
        'グラフの表示期間は開始・終了を両方入力するか、両方空にしてください（片方だけでは指定できません）。',
    }
  }
  const r = resolveEventApiRange(rf, rt, timeZone)
  if (!r.ok) return { mode: 'invalid', message: r.message }
  if (!r.from || !r.to) {
    return { mode: 'invalid', message: '開始と終了を解釈できませんでした。' }
  }
  return { mode: 'range', from: r.from, to: r.to }
}

/** Graph tab: one-line summary for collapsed range `<details>` (no `open` = default closed). */
export function summarizeGraphRangePreview(parts: ZonedRangeParts): string {
  const { rangeFromInput, rangeToInput } = zonedRangePartsToCombinedInputs(parts)
  const rf = rangeFromInput.trim()
  const rt = rangeToInput.trim()
  if (!rf && !rt) return '指定なし'
  if (!rf || !rt) return '入力中'
  return `${parts.fromDate} ～ ${parts.toDate}`
}
