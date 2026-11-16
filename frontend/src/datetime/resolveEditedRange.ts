import { validateApiRange } from './apiRangeLimit'
import { resolveEventApiRange } from './graphRange'
import { zonedRangePartsToCombinedInputs, type ZonedRangeParts } from './zonedRangeParts'

export type EditedRangeResolve =
  | { ok: true; from: string; to: string }
  | { ok: false; message: string }

/**
 * 期間の入力欄（分単位の壁時計）から、API に送る UTC の期間を決める。
 *
 * 編集していない側（`base.parts` と同じ入力）は、`base` の UTC の端点をそのまま使う。入力欄は分までしか持たず、
 * 夏時間の戻りではあいまいな時刻もあるので、組み直すと秒が落ちたり 1 時間ずれたりするため。
 * 壁時計からの組み直しと、その拒否（存在しない時刻など）は編集した側だけにかけ、順序と 90 日の上限は
 * 決まった UTC の範囲で検査する（夏時間の戻りでは、壁時計の上で終了が開始より前に見える正しい期間がある）。
 */
export function resolveEditedRange(
  parts: ZonedRangeParts,
  base: { parts: ZonedRangeParts; from: string; to: string } | null,
  timeZone: string,
  missingMessage: string,
): EditedRangeResolve {
  const { rangeFromInput, rangeToInput } = zonedRangePartsToCombinedInputs(parts)
  const fromSame = base !== null && parts.fromDate === base.parts.fromDate && parts.fromTime === base.parts.fromTime
  const toSame = base !== null && parts.toDate === base.parts.toDate && parts.toTime === base.parts.toTime
  const resolved = resolveEventApiRange(fromSame ? '' : rangeFromInput, toSame ? '' : rangeToInput, timeZone)
  if (!resolved.ok) return { ok: false, message: resolved.message }
  const from = fromSame ? base?.from : resolved.from
  const to = toSame ? base?.to : resolved.to
  if (!from || !to) return { ok: false, message: missingMessage }
  const invalid = validateApiRange({ from, to })
  return invalid ? { ok: false, message: invalid } : { ok: true, from, to }
}
