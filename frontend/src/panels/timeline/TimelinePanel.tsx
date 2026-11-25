import './TimelinePanel.css'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { apiGet } from '../../api'
import type { IncidentTimelineManualSnapshotListItem } from '../../api/schemas'
import { eventPatternsResponseSchema } from '../../api/schemas/eventPatterns'
import { validateApiRange } from '../../datetime/apiRangeLimit'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import type { ChatHandoff } from '../../hooks/chatHandoff'
import type { MetricsFocus } from '../../hooks/metricsReplay'
import { DEFAULT_TIMELINE_CONDITIONS, type TimelineConditions } from '../../routing/timelineHash'
import { useTimelineSnapshots } from '../../hooks/useTimelineSnapshots'
import { useTimelineViewController } from '../../hooks/useTimelineViewController'
import { IncidentLinkDialogProvider } from '../incidents/IncidentLinkDialog'
import { TimelineConditionBar } from './TimelineConditionBar'
import { createGuideLoader } from './eventTypeGuideLoader'
import { TimelineExportControls } from './TimelineExportControls'
import { useTimelineExportActivity } from './useTimelineExportActivity'
import { TimelineHighlights } from './TimelineHighlights'
import { TimelineImpactSection } from './TimelineImpactSection'
import { TimelineItemList } from './TimelineItemList'
import { TimelineOverviewChart } from './TimelineOverviewChart'
import { TimelineSnapshotSection } from './TimelineSnapshotSection'
import {
  defaultImpactTime,
  isMetricOmitted,
  omittedKindLabels,
  nearestItemIdToAnchor,
  omittedSourceMessages,
  sortTimelineItems,
} from './timelineModel'

/**
 * タイムライン: 開くと自動で読み込み、期間・対象・種別の条件を URL に持つ。
 * 条件バー → 件数の俯瞰 → ハイライト → 影響範囲（対象を moid で絞ったとき） → 時系列リスト → スナップショット（折りたたみ）の順に並ぶ。
 */
export function TimelinePanel({
  onError,
  onOpenSnapshotInMetrics,
  snapshotToOpen,
  onSnapshotOpenRequested,
  onOpenInMetrics,
  onOpenInChat,
  active = true,
}: {
  onError: (e: string | null) => void
  snapshotToOpen?: { id: string; nonce: number } | null
  onSnapshotOpenRequested?: () => void
  onOpenSnapshotInMetrics?: (item: IncidentTimelineManualSnapshotListItem) => void
  /** 行から「グラフで開く」。期間・vCenter・起点の目印を渡す。 */
  onOpenInMetrics?: (focus: MetricsFocus) => void
  /** 「この範囲をチャットで分析」。渡すと操作を出す（チャットを使える権限があるときだけ渡す）。期間と vCenter だけを渡す。 */
  onOpenInChat?: (handoff: ChatHandoff) => void
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
  const requestedSnapshot = useRef<number | null>(null)
  const { select: selectSnapshot } = snapshots
  useEffect(() => {
    if (!active || !snapshotToOpen || requestedSnapshot.current === snapshotToOpen.nonce) return
    requestedSnapshot.current = snapshotToOpen.nonce
    void selectSnapshot(snapshotToOpen.id)
    onSnapshotOpenRequested?.()
  }, [active, snapshotToOpen, selectSnapshot, onSnapshotOpenRequested])
  const [expandedIds, setExpandedIds] = useState<ReadonlySet<string>>(new Set())
  const [reveal, setReveal] = useState<{ id: string; nonce: number } | null>(null)
  const [guideLoader] = useState(createGuideLoader)
  const [patternTitles, setPatternTitles] = useState<ReadonlyMap<string, string>>(() => new Map())
  const requestedPatternTitles = useRef(false)
  const exportActivity = useTimelineExportActivity()

  const { data } = c
  const exportSource = c.savedView
    ? { snapshotId: c.savedView.snapshotId }
    : data && c.loadedRequest ? { request: c.loadedRequest } : null
  const { entityMoid, vcenterId } = c.conditions
  const showImpact = !c.urlIssue && validateApiRange(c.resolvedRange) === null && entityMoid && vcenterId
  const impactRange = c.loadedRange ?? c.resolvedRange
  const impactPeriod = c.impactTimelineState === 'ready' || c.impactTimelineState === 'unprocessable' ? {
    ...impactRange,
    anchor: c.conditions.anchor,
    defaultAt: defaultImpactTime(
      impactRange.from,
      data?.anchor_utc ?? c.conditions.anchor,
      data?.highlights.first_signal?.timestamp_utc,
    ),
  } : null
  const hasOmittedPatterns = (data?.highlights.omitted_patterns.length ?? 0) > 0
  useEffect(() => {
    if (!hasOmittedPatterns || requestedPatternTitles.current) return
    requestedPatternTitles.current = true
    void apiGet<unknown>('/api/event-patterns')
      .then((raw) => setPatternTitles(new Map(eventPatternsResponseSchema.parse(raw).map(({ id, title }) => [id, title]))))
      .catch(() => {
        // 定義が読めないときも、注記にはパターンの ID を出す。
      })
  }, [hasOmittedPatterns])

  const sortedItems = useMemo(() => (data ? sortTimelineItems(data.items, c.sortOrder) : []), [data, c.sortOrder])
  const listedIds = useMemo(() => new Set(data?.items.map((i) => i.id) ?? []), [data])
  // 起点は結果を取ったときのもの。条件を変えた直後に、古い結果の上へ新しい起点を描かない
  const resultSources = c.loadedRequest?.sources ?? c.conditions.sources
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
  const shownItemCount = data ? data.items.length - data.config_change_items_shown : 0
  const statusText = c.loading
    ? '読み込み中…'
    : data
      ? data.truncated
        ? `${data.total_items} 件中 ${shownItemCount} 件の出来事を表示しています${omittedNote}。`
        : `${shownItemCount} 件の出来事を表示しています${omittedNote}。`
      : ''

  return (
    <IncidentLinkDialogProvider active={active} className="panel timeline-panel">
      <TimelineConditionBar c={c} />

      <p className="timeline-status" role="status" aria-label="タイムラインの読み込み" aria-live="polite">
        {statusText}
      </p>
      <TimelineExportControls activity={exportActivity} source={exportSource} timeZone={c.timeZone} />
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
      {onOpenInChat && c.loadedRange ? (
        <ChatHandoffButton
          range={c.loadedRange}
          // 期間と同じく、表示中の結果の要求から取る（保存済みの結果の表示中は、保存した要求の条件）
          vcenterId={c.loadedRequest ? (c.loadedRequest.vcenter_id ?? '') : c.conditions.vcenterId}
          narrowedBy={narrowedConditions({ ...c.conditions, entity: c.entityInput })}
          fromSavedSnapshot={c.savedView !== null}
          onOpen={onOpenInChat}
        />
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

      <div className={c.loading ? 'timeline-results timeline-results--loading' : 'timeline-results'} aria-busy={c.loading}>
        {data && (
          <>
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
                if (validateApiRange(range) === null) c.zoomTo(range)
              }}
            />
            <TimelineHighlights
              highlights={data.highlights}
              patternTitles={patternTitles}
              listedIds={listedIds}
              includesEvents={resultSources.includes('event')}
              includesLogs={resultSources.includes('log')}
              anchorUtc={dataAnchor}
              period={{ from: data.from_utc, to: data.to_utc }}
              timeZone={c.timeZone}
              onRevealItem={revealItem}
              onFilterEntity={c.filterByEntity}
              onSetAnchor={c.setAnchor}
            />
          </>
        )}
        {showImpact && (
          <TimelineImpactSection
            vcenterId={vcenterId}
            entityMoid={entityMoid}
            period={impactPeriod}
            timelineFailed={c.impactTimelineState === 'failed'}
            timeZone={c.timeZone}
            onFilterEntity={c.filterByEntity}
          />
        )}
        {data && (
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
            {data.truncated || data.config_change_items_truncated || omittedMessages.length > 0 ? (
              <div className="timeline-notices">
                {data.truncated ? (
                  <p className="timeline-truncated" role="note">
                    {data.total_items} 件中 {shownItemCount} 件を表示しています。期間や対象を絞ってください
                  </p>
                ) : null}
                {data.config_change_items_truncated ? (
                  <p className="timeline-truncated" role="note">
                    構成変更の行は、{dataAnchor ? '起点' : '期間の終わり'}に近い {data.config_change_items_shown} 件だけを一覧に出しています
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
        )}
      </div>

      <TimelineSnapshotSection
        snapshots={snapshots}
        exportActivity={exportActivity}
        canSaveNow={c.loadedRequest !== null && !c.loading}
        showingSaved={c.savedView !== null}
        timeZone={c.timeZone}
        onOpenSnapshotInMetrics={onOpenSnapshotInMetrics}
      />
    </IncidentLinkDialogProvider>
  )
}

/** 既定から変えていて、チャットには引き継がれない条件の名前。 */
function narrowedConditions(c: TimelineConditions): string[] {
  const d = DEFAULT_TIMELINE_CONDITIONS
  const out: string[] = []
  if (c.entity.trim() !== '' || c.entityMoid) out.push('対象')
  if (c.anchor !== null) out.push('起点')
  if (c.sources.length !== d.sources.length || !d.sources.every((k) => c.sources.includes(k))) out.push('種別')
  if (c.minScore !== d.minScore) out.push('最小スコア')
  if (c.cpuThresholdPct !== d.cpuThresholdPct || c.memoryThresholdPct !== d.memoryThresholdPct) out.push('しきい値')
  return out
}

const CHAT_HANDOFF_TITLE =
  '表示中の期間（保存済みの結果なら保存した期間）と vCenter をチャットに渡します。対象・種別・起点などの絞り込みは渡らず、メッセージも自動では送りません。'

/** チャットのタブに期間と vCenter を渡す。チャットが受け付けない期間（90 日超など）は押せない。 */
function ChatHandoffButton({
  range,
  vcenterId,
  narrowedBy,
  fromSavedSnapshot,
  onOpen,
}: {
  range: { from: string; to: string }
  vcenterId: string
  narrowedBy: string[]
  fromSavedSnapshot: boolean
  onOpen: (handoff: ChatHandoff) => void
}) {
  const invalid = validateApiRange(range)
  return (
    <p>
      <button
        type="button"
        className="btn btn--gray"
        disabled={invalid !== null}
        title={invalid ? `チャットに渡せません。${invalid}` : CHAT_HANDOFF_TITLE}
        onClick={() => onOpen({ from: range.from, to: range.to, vcenterId: vcenterId || null, narrowedBy, fromSavedSnapshot })}
      >
        この範囲をチャットで分析
      </button>
    </p>
  )
}
