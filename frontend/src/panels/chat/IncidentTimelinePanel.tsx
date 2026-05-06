import { useMemo, useState } from 'react'
import type { IncidentTimeline, IncidentTimelineEntry } from '../../api/schemas'

const KIND_PRIORITY: Record<IncidentTimelineEntry['kind'], number> = {
  alert: 0,
  event: 1,
  metric: 2,
}

const DEFAULT_VISIBLE_ITEMS = 10
type SourceFilter = 'all' | IncidentTimelineEntry['kind']
type ImportanceFilter = 'all' | 'high' | 'medium' | 'low'

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

/** インシデント統合タイムラインを時刻列ごとに表示する。 */
export function IncidentTimelinePanel({ timeline }: { timeline: IncidentTimeline }) {
  const [expandedTimestamps, setExpandedTimestamps] = useState<Set<string>>(() => new Set())
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all')
  const [importanceFilter, setImportanceFilter] = useState<ImportanceFilter>('all')

  const orderedColumns = useMemo(
    () =>
      [...timeline.columns].sort((a, b) =>
        a.timestamp_utc < b.timestamp_utc ? 1 : a.timestamp_utc > b.timestamp_utc ? -1 : 0,
      ),
    [timeline.columns],
  )

  return (
    <section className="chat-panel__section" aria-label="インシデント統合タイムライン">
      <h3 className="chat-panel__timeline-title">インシデント統合タイムライン</h3>
      {orderedColumns.length === 0 ? (
        <p className="hint">表示対象のタイムラインはありません。</p>
      ) : (
        <>
          <div className="chat-panel__timeline-filters">
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
          <ul className="incident-timeline" aria-label="インシデント統合タイムライン">
            {orderedColumns.map((column) => {
              const isUsingServerSummary = column.items.length === 0
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
              const hiddenCount = isUsingServerSummary
                ? Math.max(column.hidden_count, filteredHiddenCount)
                : filteredHiddenCount
              const shownItems = isExpanded ? sortedItems : sortedItems.slice(0, DEFAULT_VISIBLE_ITEMS)
              return (
                <li
                  key={column.timestamp_utc}
                  className="incident-timeline__column"
                  aria-label={`${column.timestamp_utc} のタイムライン`}
                >
                  <p className="incident-timeline__timestamp">{column.timestamp_utc}</p>
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
        </>
      )}
    </section>
  )
}
