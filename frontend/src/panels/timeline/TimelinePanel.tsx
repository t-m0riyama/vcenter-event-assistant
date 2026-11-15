import './TimelinePanel.css'

import { useCallback, useMemo, useState } from 'react'

import type { IncidentTimelineManualSnapshotListItem } from '../../api/schemas'
import { useTimelineSnapshots } from '../../hooks/useTimelineSnapshots'
import { useTimelineViewController } from '../../hooks/useTimelineViewController'
import { TimelineConditionBar } from './TimelineConditionBar'
import type { GuideCache } from './TimelineEventGuide'
import { TimelineHighlights } from './TimelineHighlights'
import { TimelineItemList } from './TimelineItemList'
import { TimelineOverviewChart } from './TimelineOverviewChart'
import { TimelineSnapshotSection } from './TimelineSnapshotSection'
import { nearestItemIdToAnchor, sortTimelineItems, validateResolvedRange } from './timelineModel'

/**
 * タイムライン: 開くと自動で読み込み、期間・対象・種別の条件を URL に持つ。
 * 条件バー → 件数の俯瞰 → ハイライト → 時系列リスト → スナップショット（折りたたみ）の順に並ぶ。
 */
export function TimelinePanel({
  onError,
  onOpenSnapshotInMetrics,
  active = true,
}: {
  onError: (e: string | null) => void
  onOpenSnapshotInMetrics?: (item: IncidentTimelineManualSnapshotListItem) => void
  /** このタブが表示中か。表示中のときだけ URL を書き、戻ったときに読み直す。 */
  active?: boolean
}) {
  const c = useTimelineViewController(onError, { active })
  const snapshots = useTimelineSnapshots({
    onError,
    vcenterId: c.conditions.vcenterId,
    loadedRange: c.loadedRange,
    applyConditions: c.applySnapshotConditions,
  })
  const [expandedIds, setExpandedIds] = useState<ReadonlySet<string>>(new Set())
  const [reveal, setReveal] = useState<{ id: string; nonce: number } | null>(null)
  const [guideCache] = useState<GuideCache>(() => new Map())

  const { data } = c
  const sortedItems = useMemo(() => (data ? sortTimelineItems(data.items, c.sortOrder) : []), [data, c.sortOrder])
  const listedIds = useMemo(() => new Set(data?.items.map((i) => i.id) ?? []), [data])
  const nearestAnchorId = useMemo(
    () => (data ? nearestItemIdToAnchor(data.items, c.conditions.anchor) : null),
    [data, c.conditions.anchor],
  )

  const toggle = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (!next.delete(id)) next.add(id)
      return next
    })
  }, [])

  const revealItem = useCallback((id: string) => {
    setExpandedIds((prev) => new Set(prev).add(id))
    setReveal((prev) => ({ id, nonce: (prev?.nonce ?? 0) + 1 }))
  }, [])

  const statusText = c.loading
    ? '読み込み中…'
    : data
      ? data.truncated
        ? `${data.total_items} 件中 ${data.items.length} 件の出来事を表示しています。`
        : `${data.total_items} 件の出来事を表示しています。`
      : ''

  return (
    <div className="panel timeline-panel">
      <TimelineConditionBar c={c} />

      <p className="timeline-status" role="status" aria-live="polite">
        {statusText}
      </p>

      {c.error ? (
        <div className="error-banner timeline-error" role="alert">
          <p>{c.error.message}</p>
          {c.error.kind !== 'invalid' ? (
            <button type="button" className="btn btn--gray" onClick={c.refresh}>
              再読み込み
            </button>
          ) : null}
        </div>
      ) : null}

      {data ? (
        <div className={c.loading ? 'timeline-results timeline-results--loading' : 'timeline-results'} aria-busy={c.loading}>
          {c.canUndoZoom ? (
            <p>
              <button type="button" className="btn btn--gray" onClick={c.undoZoom}>
                絞り込み前の期間に戻す
              </button>
            </p>
          ) : null}
          <TimelineOverviewChart
            buckets={data.overview}
            bucketSeconds={data.bucket_seconds}
            toUtc={data.to_utc}
            anchorUtc={c.conditions.anchor}
            timeZone={c.timeZone}
            onSelectRange={(range) => {
              if (validateResolvedRange(range) === null) c.zoomTo(range)
            }}
          />
          <TimelineHighlights
            highlights={data.highlights}
            listedIds={listedIds}
            timeZone={c.timeZone}
            onRevealItem={revealItem}
            onFilterEntity={c.filterByEntity}
          />

          <section className="timeline-items" aria-label="時系列リスト">
            <div className="timeline-items__head">
              <h3 className="timeline-section-title">時系列リスト</h3>
              <label className="timeline-items__sort">
                並び順
                <select value={c.sortOrder} onChange={(e) => c.setSortOrder(e.target.value === 'asc' ? 'asc' : 'desc')}>
                  <option value="asc">古い順</option>
                  <option value="desc">新しい順</option>
                </select>
              </label>
            </div>
            {data.truncated ? (
              <p className="timeline-truncated" role="note">
                {data.total_items} 件中 {data.items.length} 件を表示しています。期間や対象を絞ってください
              </p>
            ) : null}
            {data.items.length === 0 ? (
              <div className="timeline-empty">
                <p className="table-empty">この期間に出来事はありません。</p>
                <button type="button" className="btn btn--gray" onClick={c.widen}>
                  期間を広げる
                </button>
              </div>
            ) : (
              <TimelineItemList
                items={sortedItems}
                timeZone={c.timeZone}
                nearestAnchorId={nearestAnchorId}
                expandedIds={expandedIds}
                onToggle={toggle}
                reveal={reveal}
                guideCache={guideCache}
                onFilterEntity={c.filterByEntity}
                onSetAnchor={c.setAnchor}
              />
            )}
          </section>
        </div>
      ) : null}

      <TimelineSnapshotSection
        snapshots={snapshots}
        canSaveNow={c.loadedRange !== null && !c.loading}
        timeZone={c.timeZone}
        onOpenSnapshotInMetrics={onOpenSnapshotInMetrics}
      />
    </div>
  )
}
