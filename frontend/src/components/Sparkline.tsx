/**
 * 依存ライブラリなしの軽量 SVG スパークライン。
 * recharts は重く概要タブはメインバンドルに載るため、インライン SVG で描画する。
 * 色は CSS の `color`（currentColor）に追従する。
 */
export function Sparkline({
  values,
  width = 128,
  height = 28,
}: {
  values: readonly number[]
  width?: number
  height?: number
}) {
  if (values.length < 2) return null
  const max = Math.max(...values, 1)
  const stepX = width / (values.length - 1)
  const points = values.map((v, i) => {
    const x = (i * stepX).toFixed(1)
    const y = (height - 2 - (v / max) * (height - 4)).toFixed(1)
    return `${x},${y}`
  })
  return (
    <svg
      className="sparkline"
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      aria-hidden="true"
      focusable="false"
    >
      <path d={`M0,${height} L${points.join(' L')} L${width},${height} Z`} fill="currentColor" opacity={0.14} />
      <polyline
        points={points.join(' ')}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
