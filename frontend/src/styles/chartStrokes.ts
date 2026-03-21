/**
 * Recharts は SVG の presentation attribute に `stroke` を渡す。
 * 属性値の `var(--token)` は CSS として解決されず、ブラウザ既定色になることがある。
 * チャート用ストロークはリテラル色にし、下記を `variables.css` のトークンと揃える。
 */
export const CHART_STROKE_PRIMARY = '#007aff' // --color-primary
export const CHART_STROKE_SECONDARY = '#34c759' // system green (contrast with primary line)
export const CHART_STROKE_GRID = '#dde2e8' // --color-border / --color-gray-200
