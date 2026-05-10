import { useMemo, useState } from 'react'
import type { IncidentTimeline, IncidentTimelineEntry } from '../../api/schemas'
import './IncidentTimelinePanel.css'

const KIND_PRIORITY: Record<IncidentTimelineEntry['kind'], number> = {
  alert: 0,
  event: 1,
  metric: 2,
}

const DEFAULT_VISIBLE_ITEMS = 10
type SourceFilter = 'all' | IncidentTimelineEntry['kind']
type ImportanceFilter = 'all' | 'high' | 'medium' | 'low'
type TimelineSortOrder = 'asc' | 'desc'
const SHORT_RANGE_MAX_MS = 24 * 60 * 60 * 1000

const KIND_TO_IMPORTANCE: Record<IncidentTimelineEntry['kind'], Exclude<ImportanceFilter, 'all'>> = {
  alert: 'high',
  event: 'medium',
  metric: 'low',
}

function sortTimelineItems(items: readonly IncidentTimelineEntry[]): IncidentTimelineEntry[] {
  return [...items]
    .map((item, idx) => ({ item, idx }))
    .sort((a, b) => {
      const byKind = KIND_PRIORITY[a.item.kind] - KIND_PRIORITY[b.item.kind]
      if (byKind !== 0) return byKind
      return a.idx - b.idx
    })
    .map((x) => x.item)
}

function formatTwoDigits(value: number): string {
  return String(value).padStart(2, '0')
}

function formatUtcClock(iso: string): string | null {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return null
  const hh = formatTwoDigits(date.getUTCHours())
  const mm = formatTwoDigits(date.getUTCMinutes())
  return `${hh}:${mm}`
}

function formatUtcDateClock(iso: string): string | null {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return null
  const month = formatTwoDigits(date.getUTCMonth() + 1)
  const day = formatTwoDigits(date.getUTCDate())
  const hh = formatTwoDigits(date.getUTCHours())
  const mm = formatTwoDigits(date.getUTCMinutes())
  return `${month}/${day} ${hh}:${mm}`
}

function extractUtcDateKey(iso: string): string | null {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return null
  const year = date.getUTCFullYear()
  const month = formatTwoDigits(date.getUTCMonth() + 1)
  const day = formatTwoDigits(date.getUTCDate())
  return `${year}-${month}-${day}`
}

function formatTimelineHeader(
  column: IncidentTimeline['columns'][number],
  options: { includeStartDateInHeader: boolean },
): string {
  if (!column.bucket_start_utc || !column.bucket_end_utc) {
    return column.timestamp_utc
  }
  const start = new Date(column.bucket_start_utc)
  const end = new Date(column.bucket_end_utc)
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return column.timestamp_utc
  }
  const durationMs = end.getTime() - start.getTime()
  const startClock = formatUtcClock(column.bucket_start_utc)
  const endClock = formatUtcClock(column.bucket_end_utc)
  if (!startClock || !endClock) {
    return column.timestamp_utc
  }
  const shouldIncludeStartDate = options.includeStartDateInHeader || durationMs > SHORT_RANGE_MAX_MS
  if (!shouldIncludeStartDate) {
    return `${startClock}-${endClock}`
  }
  const startDateClock = formatUtcDateClock(column.bucket_start_utc)
  if (!startDateClock) {
    return column.timestamp_utc
  }
  return `${startDateClock}-${endClock}`
}

export type IncidentTimelineSnapshotMarker = {
  readonly timestamp_utc: string
  readonly label: string
}

/** インシデント統合タイムラインを時刻列ごとに表示する。 */
export function IncidentTimelinePanel({
  timeline,
  sortOrder = 'desc',
  snapshotMarkers = [],
}: {
  timeline: IncidentTimeline
  sortOrder?: TimelineSortOrder
  /** 保存スナップショットの記録時刻をタイムライン表示範囲内で注記する。 */
  snapshotMarkers?: readonly IncidentTimelineSnapshotMarker[]
}) {
  const [expandedTimestamps, setExpandedTimestamps] = useState<Set<string>>(() => new Set())
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all')
  const [importanceFilter, setImportanceFilter] = useState<ImportanceFilter>('all')

  const orderedColumns = useMemo(
    () => [...timeline.columns].sort((a, b) => {
      const cmp = a.timestamp_utc < b.timestamp_utc ? -1 : a.timestamp_utc > b.timestamp_utc ? 1 : 0
      return sortOrder === 'asc' ? cmp : -cmp
    }),
    [sortOrder, timeline.columns],
  )

  const includeStartDateInHeader = useMemo(() => {
    const dateKeys = new Set<string>()
    for (const column of orderedColumns) {
      const source = column.bucket_start_utc ?? column.timestamp_utc
      const key = extractUtcDateKey(source)
      if (key) {
        dateKeys.add(key)
      }
      if (dateKeys.size > 1) {
        return true
      }
    }
    return false
  }, [orderedColumns])

  return (
    <section className="timeline-section" aria-label="インシデント統合タイムライン">
      <h3 className="timeline-section__title">インシデント統合タイムライン</h3>
      {orderedColumns.length === 0 ? (
        <p className="hint">表示対象のタイムラインはありません。</p>
      ) : (
        <>
          <div className="timeline-section__filters">
            <label>
              ソース
              <select
                value={sourceFilter}
                onChange={(e) => {
                  setSourceFilter(e.target.value as SourceFilter)
                }}
              >
                <option value="all">すべて</option>
                <option value="alert">Alert</option>
                <option value="event">Event</option>
                <option value="metric">Metric</option>
              </select>
            </label>
            <label>
              重要度
              <select
                value={importanceFilter}
                onChange={(e) => {
                  setImportanceFilter(e.target.value as ImportanceFilter)
                }}
              >
                <option value="all">すべて</option>
                <option value="high">高</option>
                <option value="medium">中</option>
                <option value="low">低</option>
              </select>
            </label>
          </div>
          {snapshotMarkers.length > 0 ? (
            <div
              className="incident-timeline__snapshot-markers"
              data-testid="incident-timeline-snapshot-markers"
              aria-label="スナップショット記録"
            >
              {snapshotMarkers.map((m) => (
                <span key={`${m.timestamp_utc}-${m.label}`} className="incident-timeline__snapshot-chip">
                  {formatUtcClock(m.timestamp_utc) ?? m.timestamp_utc}: {m.label}
                </span>
              ))}
            </div>
          ) : null}
          <div className="incident-timeline__scroll">
            <ul
              className="incident-timeline incident-timeline--horizontal"
              aria-label="インシデント統合タイムライン"
            >
              {orderedColumns.map((column) => {
                const isUsingServerSummary = column.items.length === 0
                const isFilterActive = sourceFilter !== 'all' || importanceFilter !== 'all'
                const allItems = isUsingServerSummary ? column.visible_items : column.items
                const filteredItems = allItems.filter((item) => {
                  const sourceMatched = sourceFilter === 'all' || item.kind === sourceFilter
                  const importanceMatched =
                    importanceFilter === 'all' || KIND_TO_IMPORTANCE[item.kind] === importanceFilter
                  return sourceMatched && importanceMatched
                })
                const sortedItems = sortTimelineItems(filteredItems)
                const isExpanded = expandedTimestamps.has(column.timestamp_utc)
                const filteredHiddenCount = Math.max(0, sortedItems.length - DEFAULT_VISIBLE_ITEMS)
                const hiddenCount =
                  isUsingServerSummary && !isFilterActive
                    ? Math.max(column.hidden_count, filteredHiddenCount)
                    : filteredHiddenCount
                const shownItems = isExpanded ? sortedItems : sortedItems.slice(0, DEFAULT_VISIBLE_ITEMS)
                return (
                  <li
                    key={column.timestamp_utc}
                    className="incident-timeline__column"
                    aria-label={`${column.timestamp_utc} のタイムライン`}
                  >
                    <p className="incident-timeline__timestamp">
                      {formatTimelineHeader(column, { includeStartDateInHeader })}
                    </p>
                    <div className="incident-timeline__items">
                      {shownItems.map((item, idx) => (
                        <span
                          key={`${item.timestamp_utc}-${item.kind}-${item.title}-${idx}`}
                          data-testid="incident-timeline-item"
                          className={`incident-timeline__item incident-timeline__item--${item.kind}`}
                        >
                          {item.title}
                        </span>
                      ))}
                    </div>
                    {!isExpanded && hiddenCount > 0 && (
                      <button
                        type="button"
                        className="btn btn--gray incident-timeline__expand-btn"
                        onClick={() => {
                          setExpandedTimestamps((prev) => new Set(prev).add(column.timestamp_utc))
                        }}
                      >
                        +{hiddenCount}件
                      </button>
                    )}
                  </li>
                )
              })}
            </ul>
          </div>
        </>
      )}
    </section>
  )
}
