import { parseApiUtcInstantMs } from './formatIsoInTimeZone'
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

/** `T23:59` の終了入力をその壁時計分の末尾（+59秒）まで含める。 */
function utcIsoThroughEndOfWallMinute(wallInput: string, utcIso: string): string {
  if (!wallInput.endsWith('T23:59')) return utcIso
  const ms = parseApiUtcInstantMs(utcIso)
  if (!Number.isFinite(ms)) return utcIso
  return new Date(ms + 59_000).toISOString()
}

/**
 * 壁時計の期間入力（表示 TZ）を API 用 UTC ISO ``from`` / ``to`` に変換する。
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
    toUtc = utcIsoThroughEndOfWallMinute(rt, iso)
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
 * メトリクスグラフ用の期間解決。両方空ならフィルタなし、片方のみは invalid。
 * イベントレート overlay と metrics で同一 bounds を使うため、イベントと同じルールを適用する。
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

/** 折りたたみ期間 `<details>` 用の一行プレビュー（未入力 / 入力中 / 範囲表示）。 */
export function summarizeGraphRangePreview(parts: ZonedRangeParts): string {
  const { rangeFromInput, rangeToInput } = zonedRangePartsToCombinedInputs(parts)
  const rf = rangeFromInput.trim()
  const rt = rangeToInput.trim()
  if (!rf && !rt) return '指定なし'
  if (!rf || !rt) return '入力中'
  return `${parts.fromDate} ～ ${parts.toDate}`
}
