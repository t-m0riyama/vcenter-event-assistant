/**
 * メトリクスグラフの Y 軸目盛り・ツールチップ用の数値整形。
 * 大きな値では `notation: 'compact'` で幅を抑え、ツールチップでは桁区切り付きで詳細を表示する。
 * メトリクスキーが `_bytes` / `_kbytes` / `_mbytes` / `_tbytes` … で終わる場合、末尾から単位を類推して正規化する。
 * - `_bytes`: 値はバイト
 * - `_kbytes` … `_mbytes`: 1 単位 = 10³ … 10⁶ B（例: `_kbytes` の 1000 → **1M** 表示）
 * - `_tbytes` 以上: 1 単位 = 10¹² … 10²⁴ B（`_tbytes` … `_ybytes`）
 * 表示は **B / K / M / G / T / P / E / Z / Y**（1000 段階・SI）。和名 compact（千・万・億）は使わない。
 */

export type ChartYAxisKind = 'metric' | 'count'

/**
 * バックエンドの値のスケール。`_mbytes` より長いサフィックスを先に判定する。
 * 指数は「バイトに直すときの 1000^exp」。
 */
export type MetricStorageScale =
  | 'bytes'
  | 'kbytes'
  | 'mbytes'
  | 'tbytes'
  | 'pbytes'
  | 'ebytes'
  | 'zbytes'
  | 'ybytes'

/** この絶対値以上は compact 表記（例: 1.2万）に切り替える（バイト系以外） */
const COMPACT_ABS_THRESHOLD = 10_000

/** `metricValueToBytes` 用: scale → 乗算は 1000^exp（SI） */
const METRIC_SCALE_EXPONENT: Record<MetricStorageScale, number> = {
  bytes: 0,
  kbytes: 1,
  mbytes: 2,
  tbytes: 4,
  pbytes: 5,
  ebytes: 6,
  zbytes: 7,
  ybytes: 8,
}

/** 表示上の段階（1000 倍ごと）。T より上も含む */
const STORAGE_STEP_SI = 1000

const compactJa = new Intl.NumberFormat('ja-JP', {
  notation: 'compact',
  maximumFractionDigits: 1,
})

const groupedIntJa = new Intl.NumberFormat('ja-JP', {
  useGrouping: true,
  maximumFractionDigits: 0,
})

const tooltipJa = new Intl.NumberFormat('ja-JP', {
  useGrouping: true,
  maximumFractionDigits: 20,
})

/**
 * メトリクスキー末尾からストレージ換算スケールを推定する。
 * `_ybytes` … `_tbytes` を `_mbytes` / `_kbytes` / `_bytes` より先に判定する。
 */
export function getMetricStorageScale(metricKey: string): MetricStorageScale | null {
  const k = metricKey.trim()
  if (k.endsWith('_ybytes')) return 'ybytes'
  if (k.endsWith('_zbytes')) return 'zbytes'
  if (k.endsWith('_ebytes')) return 'ebytes'
  if (k.endsWith('_pbytes')) return 'pbytes'
  if (k.endsWith('_tbytes')) return 'tbytes'
  if (k.endsWith('_mbytes')) return 'mbytes'
  if (k.endsWith('_kbytes')) return 'kbytes'
  if (k.endsWith('_bytes')) return 'bytes'
  return null
}

/**
 * API の生値をバイト（SI の基準）に正規化する。
 */
export function metricValueToBytes(value: number, scale: MetricStorageScale): number {
  const exp = METRIC_SCALE_EXPONENT[scale]
  return value * 1000 ** exp
}

/**
 * SI 段階の接尾辞（軸・ツールチップ共通）。B から Y まで（T より上は P, E, Z, Y）。
 */
const STORAGE_SUFFIX = ['B', 'K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y'] as const

/** 絶対値バイトを、SI（1000 倍）の段階インデックスとその段階での値に変換する */
function storageUnitIndexAndValue(bytesAbs: number): { i: number; valueInUnit: number } {
  if (bytesAbs === 0) return { i: 0, valueInUnit: 0 }
  let i = 0
  let n = bytesAbs
  while (n >= STORAGE_STEP_SI && i < STORAGE_SUFFIX.length - 1) {
    n /= STORAGE_STEP_SI
    i += 1
  }
  return { i, valueInUnit: n }
}

/**
 * Y 軸用。B〜Y まで詰めて短くする（幅を抑えるため小数は最小限）。
 */
function formatBytesAxisTick(bytes: number): string {
  if (!Number.isFinite(bytes)) return ''
  const sign = bytes < 0 ? '-' : ''
  const abs = Math.abs(bytes)
  if (abs === 0) return '0 B'
  const { i, valueInUnit } = storageUnitIndexAndValue(abs)
  const nf = new Intl.NumberFormat('ja-JP', {
    maximumFractionDigits: i === 0 ? 0 : 1,
    minimumFractionDigits: 0,
  })
  const suf = STORAGE_SUFFIX[i]
  if (i === 0) return `${sign}${nf.format(valueInUnit)} ${suf}`
  return `${sign}${nf.format(valueInUnit)}${suf}`
}

/**
 * Tooltip 用。やや詳しい桁で B〜Y 表記する。
 */
function formatBytesTooltip(bytes: number): string {
  if (!Number.isFinite(bytes)) return ''
  const sign = bytes < 0 ? '-' : ''
  const abs = Math.abs(bytes)
  if (abs === 0) return '0 B'
  const { i, valueInUnit } = storageUnitIndexAndValue(abs)
  const nf = new Intl.NumberFormat('ja-JP', {
    maximumFractionDigits: i <= 1 ? 0 : 2,
    minimumFractionDigits: 0,
  })
  const suf = STORAGE_SUFFIX[i]
  if (i === 0) return `${sign}${nf.format(valueInUnit)} ${suf}`
  return `${sign}${nf.format(valueInUnit)} ${suf}`
}

export type FormatChartTooltipOptions = {
  /** 選択中のメトリクスキー（ストレージ系の判定に使用） */
  readonly metricKey?: string
  /** Recharts の系列 `dataKey`。`evCount` のときは件数として扱いストレージ整形しない */
  readonly dataKey?: string
}

/**
 * Recharts Y 軸の `tickFormatter` 用。左軸（メトリクス）と右軸（件数）で最適化する。
 *
 * @param metricKey 左軸メトリクス選択時のみ指定（`kind === 'metric'` でストレージ系を判定）
 */
export function formatChartYAxisTick(
  value: number,
  kind: ChartYAxisKind,
  metricKey?: string,
): string {
  if (!Number.isFinite(value)) return ''
  if (kind === 'metric' && metricKey) {
    const scale = getMetricStorageScale(metricKey)
    if (scale) {
      const bytes = metricValueToBytes(value, scale)
      return formatBytesAxisTick(bytes)
    }
  }

  const abs = Math.abs(value)

  if (kind === 'metric') {
    if (abs < 10) return String(value)
    if (abs < COMPACT_ABS_THRESHOLD) return groupedIntJa.format(Math.round(value))
    return compactJa.format(value)
  }

  const intVal = Math.round(value)
  if (abs < COMPACT_ABS_THRESHOLD) return groupedIntJa.format(intVal)
  return compactJa.format(intVal)
}

/**
 * Tooltip 内の数値を読みやすく表示する。
 * 軸が短いストレージ表記のときは、こちらで桁区切りまたは詳細な単位を付ける。
 */
export function formatChartTooltipNumber(
  value: number,
  options?: FormatChartTooltipOptions,
): string {
  if (!Number.isFinite(value)) return ''
  const dataKey = options?.dataKey
  if (dataKey === 'evCount') return tooltipJa.format(value)

  const mk = options?.metricKey?.trim()
  if (mk) {
    const scale = getMetricStorageScale(mk)
    if (scale) {
      const bytes = metricValueToBytes(value, scale)
      return formatBytesTooltip(bytes)
    }
  }
  return tooltipJa.format(value)
}
