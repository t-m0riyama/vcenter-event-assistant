import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ReferenceArea,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { TimelineOverviewBucket } from '../../api/schemas'
import { formatIsoInTimeZone, parseApiUtcInstantMs } from '../../datetime/formatIsoInTimeZone'
import { useChartThemeColors } from '../../theme/useChartThemeColors'
import {
  bucketRangeLabel,
  bucketStartContaining,
  dragRange,
  type ResolvedRange,
} from './timelineModel'

type Props = {
  buckets: readonly TimelineOverviewBucket[]
  bucketSeconds: number
  toUtc: string
  anchorUtc: string | null
  timeZone: string
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
  log: number
}

function formatTick(iso: string, timeZone: string, withDate: boolean): string {
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

type SeriesDef = { key: keyof Omit<Row, 'start'>; label: string; color: string }

/**
 * 件数の俯瞰。種別ごとの積み上げ棒。棒のクリックでその範囲、ドラッグで選んだ範囲に絞る。
 * キーボード: グラフにフォーカスして左右の矢印（Shift で範囲を広げる）、Enter で絞る。
 */
export function TimelineOverviewChart({ buckets, bucketSeconds, toUtc, anchorUtc, timeZone, onSelectRange }: Props) {
  const colors = useChartThemeColors()
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(0)
  const [activeIndex, setActiveIndex] = useState<number | null>(null)
  const [selectionStart, setSelectionStart] = useState<number | null>(null)
  const [dragFrom, setDragFrom] = useState<number | null>(null)
  const [dragTo, setDragTo] = useState<number | null>(null)

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
        metric: b.metric_breach,
        log: b.log_error,
      })),
    [buckets],
  )

  // 最大値が 0 の種別は凡例に出さない（メトリクス・ログは API がまだ返さない）
  const series: SeriesDef[] = useMemo(() => {
    const all: SeriesDef[] = [
      { key: 'other', label: 'その他のイベント', color: colors.series[5] },
      { key: 'notable', label: '要注意イベント', color: colors.series[2] },
      { key: 'alert', label: 'アラート', color: colors.series[3] },
      { key: 'metric', label: 'メトリクス超過', color: colors.series[4] },
      { key: 'log', label: 'エラーログ', color: colors.series[1] },
    ]
    return all.filter((s) => rows.some((r) => r[s.key] > 0))
  }, [colors, rows])

  const withDate = useMemo(() => {
    if (rows.length < 2) return false
    return parseApiUtcInstantMs(toUtc) - parseApiUtcInstantMs(rows[0].start) > 24 * 3_600_000
  }, [rows, toUtc])

  const anchorBucket = useMemo(
    () => bucketStartContaining(buckets, bucketSeconds, anchorUtc),
    [buckets, bucketSeconds, anchorUtc],
  )

  const rangeOf = useCallback(
    (a: number, b: number) =>
      dragRange(rows[Math.min(a, b)].start, rows[Math.max(a, b)].start, bucketSeconds, toUtc),
    [rows, bucketSeconds, toUtc],
  )

  const describe = (a: number, b: number): string => {
    const r = rangeOf(a, b)
    const count = rows.slice(Math.min(a, b), Math.max(a, b) + 1).reduce(
      (sum, row) => sum + row.other + row.notable + row.alert + row.metric + row.log,
      0,
    )
    return `${formatIsoInTimeZone(r.from, timeZone)} ～ ${formatIsoInTimeZone(r.to, timeZone)}、${count} 件。Enter で期間をこの範囲に絞ります。`
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
      setSelectionStart(null)
      return
    } else if (e.key === 'Escape') {
      setActiveIndex(null)
      setSelectionStart(null)
      return
    }
    if (next === null) return
    e.preventDefault()
    if (e.shiftKey) setSelectionStart((s) => s ?? activeIndex ?? next)
    else setSelectionStart(null)
    setActiveIndex(next)
  }

  const finishPointer = () => {
    if (dragFrom !== null && dragTo !== null && rows.length > 0) {
      onSelectRange(rangeOf(dragFrom, dragTo))
    }
    setDragFrom(null)
    setDragTo(null)
  }

  const indexOf = (state: unknown): number | null => {
    const idx = (state as { activeTooltipIndex?: number | string } | null)?.activeTooltipIndex
    const n = typeof idx === 'string' ? Number(idx) : idx
    return typeof n === 'number' && Number.isInteger(n) && n >= 0 && n < rows.length ? n : null
  }

  if (rows.length === 0) return null

  const highlightFrom = dragFrom !== null && dragTo !== null ? Math.min(dragFrom, dragTo) : activeIndex === null ? null : Math.min(selectionStart ?? activeIndex, activeIndex)
  const highlightTo = dragFrom !== null && dragTo !== null ? Math.max(dragFrom, dragTo) : activeIndex === null ? null : Math.max(selectionStart ?? activeIndex, activeIndex)
  const chartWidth = width > 0 ? width : FALLBACK_WIDTH

  return (
    <section className="timeline-overview" aria-label="件数の俯瞰">
      <h3 className="timeline-section-title">件数の俯瞰</h3>
      <div
        ref={wrapRef}
        className="timeline-overview__chart"
        tabIndex={0}
        role="group"
        aria-label="件数の俯瞰グラフ。クリックでその時間帯、ドラッグで選んだ範囲に期間を絞ります。キーボードは左右の矢印で時間帯を選び、Enter で絞ります。"
        onKeyDown={onKeyDown}
        onBlur={() => {
          setActiveIndex(null)
          setSelectionStart(null)
        }}
      >
        <BarChart
          width={chartWidth}
          height={CHART_HEIGHT}
          data={rows}
          margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
          barCategoryGap={1}
          onMouseDown={(state) => {
            const i = indexOf(state)
            if (i !== null) {
              setDragFrom(i)
              setDragTo(i)
            }
          }}
          onMouseMove={(state) => {
            const i = indexOf(state)
            if (dragFrom !== null && i !== null) setDragTo(i)
          }}
          onMouseUp={finishPointer}
          onMouseLeave={() => {
            setDragFrom(null)
            setDragTo(null)
          }}
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
          <Tooltip
            cursor={{ fill: colors.grid, fillOpacity: 0.35 }}
            content={({ active, payload, label }) =>
              active && payload && payload.length > 0 ? (
                <div className="timeline-overview__tooltip">
                  <strong>{bucketRangeLabel(String(label), bucketSeconds, toUtc, timeZone)}</strong>
                  <ul>
                    {payload.map((p) => (
                      <li key={String(p.dataKey)}>
                        {String(p.name)}: {String(p.value)}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null
            }
          />
          <Legend />
          {series.map((s) => (
            <Bar key={s.key} dataKey={s.key} name={s.label} stackId="count" fill={s.color} isAnimationActive={false} />
          ))}
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
        </BarChart>
        <div className="visually-hidden timeline-overview__announce" aria-live="polite">
          {activeIndex === null ? '' : describe(selectionStart ?? activeIndex, activeIndex)}
        </div>
      </div>
    </section>
  )
}
