import './TimelinePanel.css'

import { useCallback, useMemo, useState } from 'react'

import type { IncidentTimelineManualSnapshotListItem } from '../../api/schemas'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import type { MetricsFocus } from '../../hooks/metricsReplay'
import { useTimelineSnapshots } from '../../hooks/useTimelineSnapshots'
import { useTimelineViewController } from '../../hooks/useTimelineViewController'
import { TimelineConditionBar } from './TimelineConditionBar'
import { createGuideLoader } from './eventTypeGuideLoader'
import { TimelineHighlights } from './TimelineHighlights'
import { TimelineItemList } from './TimelineItemList'
import { TimelineOverviewChart } from './TimelineOverviewChart'
import { TimelineSnapshotSection } from './TimelineSnapshotSection'
import {
  isMetricOmitted,
  omittedKindLabels,
  nearestItemIdToAnchor,
  omittedSourceMessages,
  sortTimelineItems,
  validateResolvedRange,
} from './timelineModel'

/**
 * タイムライン: 開くと自動で読み込み、期間・対象・種別の条件を URL に持つ。
 * 条件バー → 件数の俯瞰 → ハイライト → 時系列リスト → スナップショット（折りたたみ）の順に並ぶ。
 */
export function TimelinePanel({
  onError,
  onOpenSnapshotInMetrics,
  onOpenInMetrics,
  active = true,
}: {
  onError: (e: string | null) => void
  onOpenSnapshotInMetrics?: (item: IncidentTimelineManualSnapshotListItem) => void
  /** 行から「グラフで開く」。期間・vCenter・起点の目印を渡す。 */
  onOpenInMetrics?: (focus: MetricsFocus) => void
  /** このタブが表示中か。表示中のときだけ URL を書き、戻ったときに読み直す。 */
  active?: boolean
}) {
  const c = useTimelineViewController(onError, { active })
  const snapshots = useTimelineSnapshots({
    onError,
    vcenterId: c.conditions.vcenterId,
    loadedRange: c.loadedRange,
    loadedRequest: c.loadedRequest,
    applyConditions: c.applySnapshotConditions,
    applyViewRequest: c.applyViewRequest,
    showSavedResult: c.showSavedResult,
    getIntent: c.getIntent,
  })
  const [expandedIds, setExpandedIds] = useState<ReadonlySet<string>>(new Set())
  const [reveal, setReveal] = useState<{ id: string; nonce: number } | null>(null)
  const [guideLoader] = useState(createGuideLoader)

  const { data } = c
  const sortedItems = useMemo(() => (data ? sortTimelineItems(data.items, c.sortOrder) : []), [data, c.sortOrder])
  const listedIds = useMemo(() => new Set(data?.items.map((i) => i.id) ?? []), [data])
  // 起点は結果を取ったときのもの。条件を変えた直後に、古い結果の上へ新しい起点を描かない
  const dataAnchor = data?.anchor_utc ?? null
  const nearestAnchorId = useMemo(
    () => (data ? nearestItemIdToAnchor(data.items, dataAnchor) : null),
    [data, dataAnchor],
  )

  const omittedMessages = useMemo(() => omittedSourceMessages(data?.omitted_sources ?? []), [data])
  const metricOmitted = useMemo(() => isMetricOmitted(data?.omitted_sources ?? []), [data])

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

  // 種別を省いたときは、「N 件の出来事」が省いた種別を含まないことを添える（ライブ領域でも読み上げる）
  const omittedNote = data && data.omitted_sources.length > 0 ? `（${omittedKindLabels(data.omitted_sources).join('・')}は省いています）` : ''
  const statusText = c.loading
    ? '読み込み中…'
    : data
      ? data.truncated
        ? `${data.total_items} 件中 ${data.items.length} 件の出来事を表示しています${omittedNote}。`
        : `${data.total_items} 件の出来事を表示しています${omittedNote}。`
      : ''

  return (
    <div className="panel timeline-panel">
      <TimelineConditionBar c={c} />

      <p className="timeline-status" role="status" aria-live="polite">
        {statusText}
      </p>
      {c.notice ? (
        <p className="timeline-truncated" role="note" aria-label="読み込みの注記">
          {c.notice}
        </p>
      ) : null}
      {c.savedView ? (
        <div className="timeline-saved-banner" role="note" aria-label="保存時点の内容">
          <p>
            <strong>保存時点の内容を表示しています。</strong>
            保存した日時: {formatIsoInTimeZone(c.savedView.savedAt, c.timeZone)}（{c.timeZone}）。
            現在のデータとは異なります。
          </p>
          <p className="timeline-saved-banner__hint">
            元のイベント・ログ・メトリクスが保持期間を過ぎていると、行の「イベントで開く」「ログで開く」「グラフで開く」の先は空になります。
            「この対象で絞る」「ここを起点にする」は、現在のデータでの再集計になります。
          </p>
          <p className="timeline-saved-banner__memo">運用メモ: {c.savedView.note}</p>
          <button type="button" className="btn btn--gray" onClick={c.reaggregate}>
            現在のデータで再集計
          </button>
        </div>
      ) : null}
      {c.loadedRange ? (
        <p className="timeline-loaded-range">
          {c.savedView ? '保存した期間' : '読み込んだ期間'}: {formatIsoInTimeZone(c.loadedRange.from, c.timeZone)} ～{' '}
          {formatIsoInTimeZone(c.loadedRange.to, c.timeZone)}（{c.timeZone}）
        </p>
      ) : null}

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
            anchorUtc={dataAnchor}
            timeZone={c.timeZone}
            metricOmitted={metricOmitted}
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
            {data.truncated || omittedMessages.length > 0 ? (
              <div className="timeline-notices">
                {data.truncated ? (
                  <p className="timeline-truncated" role="note">
                    {data.total_items} 件中 {data.items.length} 件を表示しています。期間や対象を絞ってください
                  </p>
                ) : null}
                {omittedMessages.map((message) => (
                  <p key={message} className="timeline-truncated" role="note">
                    {message}
                  </p>
                ))}
              </div>
            ) : null}
            {data.items.length === 0 ? (
              <div className="timeline-empty">
                {omittedMessages.length > 0 ? (
                  // 期間を広げると省かれる件数がさらに増えるので、広げるボタンは出さない
                  <p className="table-empty">この期間に、一覧へ表示できる出来事はありません。期間を短くするか、対象を絞ってください。</p>
                ) : (
                  <>
                    <p className="table-empty">この期間に出来事はありません。</p>
                    <button type="button" className="btn btn--gray" onClick={c.widen}>
                      期間を広げる
                    </button>
                  </>
                )}
              </div>
            ) : (
              <TimelineItemList
                items={sortedItems}
                timeZone={c.timeZone}
                nearestAnchorId={nearestAnchorId}
                expandedIds={expandedIds}
                onToggle={toggle}
                reveal={reveal}
                guideLoader={guideLoader}
                onFilterEntity={c.filterByEntity}
                onSetAnchor={c.setAnchor}
                onOpenInMetrics={onOpenInMetrics}
              />
            )}
          </section>
        </div>
      ) : null}

      <TimelineSnapshotSection
        snapshots={snapshots}
        canSaveNow={c.loadedRequest !== null && !c.loading}
        showingSaved={c.savedView !== null}
        timeZone={c.timeZone}
        onOpenSnapshotInMetrics={onOpenSnapshotInMetrics}
      />
    </div>
  )
}
