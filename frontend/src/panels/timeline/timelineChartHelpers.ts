import { useState } from 'react'

import { parseApiUtcInstantMs } from '../../datetime/formatIsoInTimeZone'

/** 指定タイムゾーンの暦日（YYYY-MM-DD）。 */
export function calendarDay(iso: string, timeZone: string): string {
  const d = new Date(parseApiUtcInstantMs(iso))
  try {
    return new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d)
  } catch {
    return d.toISOString().slice(0, 10)
  }
}

/** 期間が（指定タイムゾーンの）日付をまたぐか。 */
export function spansCalendarDays(startUtc: string, toUtc: string, timeZone: string): boolean {
  return calendarDay(startUtc, timeZone) !== calendarDay(toUtc, timeZone)
}

export function formatTick(iso: string, timeZone: string, withDate: boolean): string {
  const d = new Date(parseApiUtcInstantMs(iso))
  try {
    return new Intl.DateTimeFormat('ja-JP', {
      ...(withDate ? { month: 'numeric', day: 'numeric' } : {}),
      hour: '2-digit',
      minute: '2-digit',
      timeZone,
    }).format(d)
  } catch {
    return d.toISOString().slice(11, 16)
  }
}

/**
 * ポインタで棒を選ぶ操作（押す → 動かす → 離す）。同じ棒で離せばクリック、別の棒で離せばドラッグ。
 * 棒の添字だけを扱う（recharts の座標から添字を出すのは呼び出し側）。
 * `range` は押している間の選択中の範囲（小さい添字, 大きい添字）で、押していなければ null。
 */
export function usePointerRangeSelection(onSelect: (from: number, to: number) => void, resetKey = '') {
  // 押している間に棒の並びが変わったら（応答の差し替え）、その操作は無かったことにする
  const [state, setState] = useState<{ key: string; from: number; to: number } | null>(null)
  const drag = state && state.key === resetKey ? state : null
  return {
    range: drag ? ([Math.min(drag.from, drag.to), Math.max(drag.from, drag.to)] as const) : null,
    down: (i: number) => setState({ key: resetKey, from: i, to: i }),
    move: (i: number) => setState((d) => (d && d.key === resetKey ? { ...d, to: i } : d)),
    up: () => {
      if (drag) onSelect(drag.from, drag.to)
      setState(null)
    },
    cancel: () => setState(null),
  }
}
