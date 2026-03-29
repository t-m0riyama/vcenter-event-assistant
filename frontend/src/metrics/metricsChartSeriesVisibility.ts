/**
 * メトリクスグラフの系列表示／非表示（Recharts `Line` の `hide`）用の純関数。
 */

/** 非表示にしたい dataKey の集合を、1 キー分トグルした新しい Set を返す（入力は破壊しない）。 */
export function toggleHiddenSeriesDataKey(
  hidden: ReadonlySet<string>,
  dataKey: string,
): Set<string> {
  const next = new Set(hidden)
  if (next.has(dataKey)) {
    next.delete(dataKey)
  } else {
    next.add(dataKey)
  }
  return next
}

/** Recharts 凡例 payload の dataKey を安全に string 化。トグルに使えないときは null。 */
export function legendDataKeyToString(dataKey: unknown): string | null {
  if (dataKey === null || dataKey === undefined) {
    return null
  }
  if (typeof dataKey === 'string') {
    return dataKey
  }
  if (typeof dataKey === 'number' && Number.isFinite(dataKey)) {
    return String(dataKey)
  }
  return null
}

export type BuildMetricsChartSeriesIdentityKeyParams = {
  metricKey: string
  chartMode: 'single' | 'host'
  metricSeriesDataKeys: readonly string[]
  showEventLine: boolean
}

/**
 * 系列構成が変わったときに非表示状態をリセットするための安定キー。
 * 文字列が変われば `useEffect` で hidden をクリアする。
 */
export function buildMetricsChartSeriesIdentityKey(
  params: BuildMetricsChartSeriesIdentityKeyParams,
): string {
  const sortedKeys = [...params.metricSeriesDataKeys].sort()
  return JSON.stringify({
    metricKey: params.metricKey,
    chartMode: params.chartMode,
    metricSeriesDataKeys: sortedKeys,
    showEventLine: params.showEventLine,
  })
}
