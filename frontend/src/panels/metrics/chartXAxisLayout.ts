/**
 * チャート幅に応じた X 軸の目盛り密度（重なり防止）。
 * `minTickGap` は大きいほど目盛りが間引かれ、`tickCount` は目安の本数上限。
 */

const MIN_TICK_GAP_MIN = 28
const MIN_TICK_GAP_MAX = 56

const TICK_COUNT_MIN = 4
const TICK_COUNT_MAX = 8

/** 斜めティック・軸ラベル用の `LineChart.margin.bottom`（px） */
const BOTTOM_MARGIN_MIN = 52
const BOTTOM_MARGIN_MAX = 68

/**
 * コンテナ幅（px）から `LineChart` の下余白を返す。狭いほど斜めラベルが縦に重なりやすいため余白を広げる。
 * 未計測時は中間付近。
 */
export function xAxisBottomMarginForWidth(widthPx: number): number {
  if (!Number.isFinite(widthPx) || widthPx <= 0) return 58
  const t = Math.min(1, Math.max(0, (920 - widthPx) / 560))
  return Math.round(BOTTOM_MARGIN_MIN + t * (BOTTOM_MARGIN_MAX - BOTTOM_MARGIN_MIN))
}

/**
 * コンテナ幅（px）から `XAxis` の `minTickGap` を返す。未計測時は中間値。
 */
export function xAxisMinTickGapForWidth(widthPx: number): number {
  if (!Number.isFinite(widthPx) || widthPx <= 0) return 40
  const t = Math.min(1, Math.max(0, (920 - widthPx) / 560))
  return Math.round(MIN_TICK_GAP_MIN + t * (MIN_TICK_GAP_MAX - MIN_TICK_GAP_MIN))
}

/**
 * コンテナ幅（px）から `XAxis` の `tickCount` を返す。
 */
export function xAxisTickCountForWidth(widthPx: number): number {
  if (!Number.isFinite(widthPx) || widthPx <= 0) return 6
  const n = Math.floor(widthPx / 96)
  return Math.min(TICK_COUNT_MAX, Math.max(TICK_COUNT_MIN, n))
}
