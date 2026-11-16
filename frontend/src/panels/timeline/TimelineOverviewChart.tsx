import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import {
  Bar,
  Cell,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceArea,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { TimelineOverviewBucket } from '../../api/schemas'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { useChartThemeColors } from '../../theme/useChartThemeColors'
import {
  bucketRangeLabel,
  bucketStartContaining,
  dragRange,
  type ResolvedRange,
} from './timelineModel'
import { formatTick, spansCalendarDays, usePointerRangeSelection } from './timelineChartHelpers'

type Props = {
  buckets: readonly TimelineOverviewBucket[]
  bucketSeconds: number
  toUtc: string
  anchorUtc: string | null
  timeZone: string
  /** メトリクスを一覧から省いたとき true。`metric_breach` は当てにならないので系列を出さない。 */
  metricOmitted?: boolean
  onSelectRange: (range: ResolvedRange) => void
}

const CHART_HEIGHT = 220
/** 幅を測れない環境（テスト）で使う幅。 */
const FALLBACK_WIDTH = 640

type Row = {
  start: string
  other: number
  notable: number
  alert: number
  metric: number
  /** 帯用: 超過区間のある時間帯は 1、無ければ 0（高さは固定で、濃さに区間の数を出す）。 */
  band: number
  log: number
}

type SeriesKey = Exclude<keyof Omit<Row, 'start'>, 'metric' | 'band'>
type SeriesDef = { key: SeriesKey; label: string; color: string; unit: string }

/** 右の軸に出すエラーログの系列名（積み上げの棒とは軸が違うことを凡例で伝える）。 */
const LOG_LABEL = 'エラーログ（件・右の軸）'
/** `metric_breach` は「その時間帯にかかっている超過区間の数」で、出来事の件数とは意味が違う。 */
const METRIC_LABEL = 'メトリクス超過'
const BAND_HEIGHT = 40
/** 帯の濃さの下限（区間が 1 つでも、色が見える濃さ）。 */
const BAND_MIN_OPACITY = 0.35
const RIGHT_AXIS = 'right'

/**
 * 件数の俯瞰。種別ごとの積み上げ棒。棒のクリックでその範囲、ドラッグで選んだ範囲に絞る。
 * キーボード: グラフにフォーカスして左右の矢印（Shift で範囲を広げる）、Enter で絞る。
 */
export function TimelineOverviewChart({
  buckets,
  bucketSeconds,
  toUtc,
  anchorUtc,
  timeZone,
  metricOmitted = false,
  onSelectRange,
}: Props) {
  const colors = useChartThemeColors()
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(0)

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const update = () => setWidth(el.clientWidth)
    update()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const rows: Row[] = useMemo(
    () =>
      buckets.map((b) => ({
        start: b.bucket_start_utc,
        other: Math.max(0, b.event_total - b.event_notable),
        notable: b.event_notable,
        alert: b.alert,
        metric: metricOmitted ? 0 : b.metric_breach,
        band: !metricOmitted && b.metric_breach > 0 ? 1 : 0,
        log: b.log_error,
      })),
    [buckets, metricOmitted],
  )

  // キーボードの選択は、バケットの並び（本数・開始・幅）の鍵つきで持つ。並びが変わったら
  // （絞り込みで細かい幅の応答に差し替わるなど）、古い添字は使わず選択を解除したことにする
  const bucketKey = `${rows.length}|${rows[0]?.start ?? ''}|${bucketSeconds}`
  const [selection, setSelection] = useState<{ key: string; active: number | null; start: number | null }>({
    key: bucketKey,
    active: null,
    start: null,
  })
  const inRange = (i: number | null) => (i !== null && i >= 0 && i < rows.length ? i : null)
  const current = selection.key === bucketKey ? selection : { key: bucketKey, active: null, start: null }
  const activeIndex = inRange(current.active)
  const selectionStart = activeIndex === null ? null : inRange(current.start)

  // 最大値が 0 の種別は凡例に出さない。ログは件数が桁違いに多くなりうるので、積み上げの棒にはせず、
  // 右の軸の折れ線にする（左の軸がログに引きずられて、ほかの種別の棒が潰れるのを避ける）
  const series: SeriesDef[] = useMemo(() => {
    const all: SeriesDef[] = [
      { key: 'other', label: 'その他のイベント', color: colors.series[5], unit: '件' },
      { key: 'notable', label: '要注意イベント', color: colors.series[2], unit: '件' },
      { key: 'alert', label: 'アラート', color: colors.series[3], unit: '件' },
      { key: 'log', label: LOG_LABEL, color: colors.series[1], unit: '件' },
    ]
    return all.filter((s) => rows.some((r) => r[s.key] > 0))
  }, [colors, rows])
  const barSeries = series.filter((s) => s.key !== 'log')
  const logSeries = series.find((s) => s.key === 'log') ?? null
  // メトリクス超過は積み上げに入れず、グラフの下の帯に描く（出来事の件数と足さずに、時間帯を見比べられる）
  const hasMetric = rows.some((r) => r.metric > 0)
  const maxMetric = Math.max(1, ...rows.map((r) => r.metric))

  // 表示する期間が日付をまたぐときは、目盛りに日付を出す（期間の長さではなく、またぐかどうかで決める）
  const withDate = useMemo(
    () => rows.length > 0 && spansCalendarDays(rows[0].start, toUtc, timeZone),
    [rows, toUtc, timeZone],
  )

  const anchorBucket = useMemo(
    () => bucketStartContaining(buckets, bucketSeconds, anchorUtc),
    [buckets, bucketSeconds, anchorUtc],
  )

  const rangeOf = useCallback(
    (a: number, b: number) => {
      const last = rows.length - 1
      const lo = Math.min(Math.max(Math.min(a, b), 0), last)
      const hi = Math.min(Math.max(Math.max(a, b), 0), last)
      return dragRange(rows[lo].start, rows[hi].start, bucketSeconds, toUtc)
    },
    [rows, bucketSeconds, toUtc],
  )

  const pointer = usePointerRangeSelection((a, b) => {
    if (a < rows.length && b < rows.length) onSelectRange(rangeOf(a, b))
  }, bucketKey)

  const describe = (a: number, b: number): string => {
    const r = rangeOf(a, b)
    const picked = rows.slice(Math.min(a, b), Math.max(a, b) + 1)
    const sum = (pick: (row: Row) => number) => picked.reduce((total, row) => total + pick(row), 0)
    // メトリクス超過は区間の数で、出来事の件数とは足さない（区間は複数の時間帯にまたがって数えられる）
    const parts = [`出来事 ${sum((row) => row.other + row.notable + row.alert + row.log)} 件`]
    // 区間の数は時間帯ごとの数の合計ではないので、範囲の中で最も多い時間帯の値を読み上げる
    if (hasMetric) parts.push(`メトリクス超過 ${Math.max(...picked.map((row) => row.metric))} 区間`)
    if (logSeries) parts.push(`うちエラーログ ${sum((row) => row.log)} 件`)
    return `${formatIsoInTimeZone(r.from, timeZone)} ～ ${formatIsoInTimeZone(r.to, timeZone)}、${parts.join('、')}。Enter で期間をこの範囲に絞ります。`
  }

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (rows.length === 0) return
    const last = rows.length - 1
    let next: number | null = null
    if (e.key === 'ArrowRight') next = Math.min(last, (activeIndex ?? -1) + 1)
    else if (e.key === 'ArrowLeft') next = Math.max(0, (activeIndex ?? 1) - 1)
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = last
    else if (e.key === 'Enter' && activeIndex !== null) {
      e.preventDefault()
      onSelectRange(rangeOf(selectionStart ?? activeIndex, activeIndex))
      setSelection({ key: bucketKey, active: activeIndex, start: null })
      return
    } else if (e.key === 'Escape') {
      setSelection({ key: bucketKey, active: null, start: null })
      return
    }
    if (next === null) return
    e.preventDefault()
    setSelection({
      key: bucketKey,
      active: next,
      start: e.shiftKey ? (selectionStart ?? activeIndex ?? next) : null,
    })
  }

  const indexOf = (state: unknown): number | null => {
    const idx = (state as { activeTooltipIndex?: number | string } | null)?.activeTooltipIndex
    const n = typeof idx === 'string' ? Number(idx) : idx
    return typeof n === 'number' && Number.isInteger(n) && n >= 0 && n < rows.length ? n : null
  }

  if (rows.length === 0) return null
  const pointerHandlers = {
    onMouseDown: (state: unknown) => {
      const i = indexOf(state)
      if (i !== null) pointer.down(i)
    },
    onMouseMove: (state: unknown) => {
      const i = indexOf(state)
      if (i !== null) pointer.move(i)
    },
    onMouseUp: pointer.up,
    onMouseLeave: pointer.cancel,
  }

  const dragging = pointer.range
  const highlightFrom = dragging ? dragging[0] : activeIndex === null ? null : Math.min(selectionStart ?? activeIndex, activeIndex)
  const highlightTo = dragging ? dragging[1] : activeIndex === null ? null : Math.max(selectionStart ?? activeIndex, activeIndex)
  const chartWidth = width > 0 ? width : FALLBACK_WIDTH

  return (
    <section className="timeline-overview" aria-label="件数の俯瞰">
      <h3 className="timeline-section-title">件数の俯瞰</h3>
      <p id="timeline-overview-help" className="visually-hidden">
        クリックでその時間帯、ドラッグで選んだ範囲に期間を絞ります。キーボードでは、左右の矢印で時間帯を選び、Shift を押しながら矢印で範囲を広げ、Enter で期間を絞ります。Escape で選択をやめます。
      </p>
      <div
        ref={wrapRef}
        className="timeline-overview__chart"
        tabIndex={0}
        role="application"
        aria-label="件数の俯瞰グラフ"
        aria-describedby="timeline-overview-help"
        onKeyDown={onKeyDown}
        onBlur={() => setSelection({ key: bucketKey, active: null, start: null })}
      >
        <ComposedChart
          width={chartWidth}
          height={CHART_HEIGHT}
          data={rows}
          margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
          barCategoryGap={1}
          {...pointerHandlers}
        >
          <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="start"
            tick={{ fill: colors.axisTick, fontSize: 11 }}
            tickFormatter={(v: string) => formatTick(v, timeZone, withDate)}
            minTickGap={24}
            stroke={colors.grid}
          />
          <YAxis allowDecimals={false} width={32} tick={{ fill: colors.axisTick, fontSize: 11 }} stroke={colors.grid} />
          {logSeries ? (
            <YAxis
              yAxisId={RIGHT_AXIS}
              orientation="right"
              allowDecimals={false}
              width={40}
              tick={{ fill: logSeries.color, fontSize: 11 }}
              stroke={logSeries.color}
            />
          ) : null}
          <Tooltip
            cursor={{ fill: colors.grid, fillOpacity: 0.35 }}
            content={({ active, payload, label }) =>
              active && payload && payload.length > 0 ? (
                <div className="timeline-overview__tooltip">
                  <strong>{bucketRangeLabel(String(label), bucketSeconds, toUtc, timeZone)}</strong>
                  <ul>
                    {payload.map((p) => (
                      <li key={String(p.dataKey)}>
                        {String(p.name)}: {String(p.value)} {series.find((d) => d.key === p.dataKey)?.unit ?? '件'}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null
            }
          />
          <Legend />
          {barSeries.map((s) => (
            <Bar key={s.key} dataKey={s.key} name={s.label} stackId="count" fill={s.color} isAnimationActive={false} />
          ))}
          {logSeries ? (
            <Line
              yAxisId={RIGHT_AXIS}
              type="monotone"
              dataKey="log"
              name={logSeries.label}
              stroke={logSeries.color}
              strokeWidth={2}
              strokeDasharray="5 3"
              dot={{ r: 2 }}
              isAnimationActive={false}
            />
          ) : null}
          {anchorBucket ? <ReferenceLine x={anchorBucket} stroke={colors.primary} strokeWidth={2} label={{ value: '起点', fill: colors.primary, fontSize: 11, position: 'top' }} /> : null}
          {highlightFrom !== null && highlightTo !== null ? (
            <ReferenceArea
              x1={rows[highlightFrom].start}
              x2={rows[highlightTo].start}
              fill={colors.primary}
              fillOpacity={0.18}
              ifOverflow="visible"
            />
          ) : null}
        </ComposedChart>
        {hasMetric ? (
          <div className="timeline-overview__band">
            <p className="timeline-overview__band-label">
              {METRIC_LABEL}（グラフの下の帯。色が濃いほど、その時間帯にかかっている超過区間の数が多い。出来事の件数とは別の数です）
            </p>
            <ComposedChart
              width={chartWidth}
              height={BAND_HEIGHT}
              data={rows}
              margin={{ top: 0, right: 8, left: 0, bottom: 0 }}
              barCategoryGap={1}
              {...pointerHandlers}
            >
              <XAxis dataKey="start" hide />
              <YAxis width={32} domain={[0, 1]} tick={false} tickLine={false} axisLine={false} />
              {logSeries ? <YAxis yAxisId={RIGHT_AXIS} orientation="right" width={40} tick={false} tickLine={false} axisLine={false} /> : null}
              <Tooltip
                cursor={{ fill: colors.grid, fillOpacity: 0.35 }}
                content={({ active, payload, label }) => {
                  const row = payload?.[0]?.payload as Row | undefined
                  return active && row ? (
                    <div className="timeline-overview__tooltip">
                      <strong>{bucketRangeLabel(String(label), bucketSeconds, toUtc, timeZone)}</strong>
                      <p className="timeline-overview__tooltip-note">
                        {METRIC_LABEL}: {row.metric} 区間（この時間帯にかかっている超過区間の数。出来事の件数ではありません）
                      </p>
                    </div>
                  ) : null
                }}
              />
              <Bar dataKey="band" name={METRIC_LABEL} fill={colors.series[4]} isAnimationActive={false}>
                {rows.map((r) => (
                  <Cell
                    key={r.start}
                    fillOpacity={BAND_MIN_OPACITY + (1 - BAND_MIN_OPACITY) * Math.min(1, r.metric / maxMetric)}
                  />
                ))}
              </Bar>
              {anchorBucket ? <ReferenceLine x={anchorBucket} stroke={colors.primary} strokeWidth={2} /> : null}
              {highlightFrom !== null && highlightTo !== null ? (
                <ReferenceArea
                  x1={rows[highlightFrom].start}
                  x2={rows[highlightTo].start}
                  fill={colors.primary}
                  fillOpacity={0.18}
                  ifOverflow="visible"
                />
              ) : null}
            </ComposedChart>
          </div>
        ) : null}
        <div className="visually-hidden timeline-overview__announce" aria-live="polite">
          {activeIndex === null ? '' : describe(selectionStart ?? activeIndex, activeIndex)}
        </div>
      </div>
    </section>
  )
}
