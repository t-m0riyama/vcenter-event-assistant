import { useCallback, useRef, useState } from 'react'
import { ZodError } from 'zod'

import { ApiError, apiGet, apiPost } from '../api'
import { getManualSnapshotDetail } from '../api/incidentTimelineSnapshots'
import { buildIncidentTimelineBuildRequestPayload } from '../api/buildIncidentTimelineBuildRequestPayload'
import {
  incidentTimelineManualSnapshotCreateRequestSchema,
  incidentTimelineManualSnapshotCreateResponseSchema,
  incidentTimelineManualSnapshotListResponseSchema,
  type IncidentTimelineManualSnapshotListItem,
  type IncidentTimelineViewRequest,
  type SavedIncidentTimelineViewRequest,
} from '../api/schemas'
import type { ResolvedRange } from '../panels/timeline/timelineModel'
import { SAVED_RESULT_UNREADABLE_NOTICE, type SavedViewState } from './useTimelineViewController'
import { toErrorMessage } from '../utils/errors'
import {
  DEFAULT_METRIC_THRESHOLD_CPU_PCT,
  DEFAULT_METRIC_THRESHOLD_MEMORY_PCT,
} from './periodMetricThresholdDefaults'

/** 応答の形が想定と違う（zod の検証に失敗した）ときに、生の検証エラーの代わりに出す文言。 */
function snapshotErrorMessage(e: unknown, what: string): string {
  if (e instanceof ZodError) return `${what}を読み込めませんでした（サーバの応答が想定の形式と異なります）。`
  return toErrorMessage(e)
}

/** 保存する結果が大きすぎて 413 になったときの文言。 */
export const SNAPSHOT_TOO_LARGE_MESSAGE =
  '保存する結果が大きすぎます。期間を狭めるか、種別を減らしてからもう一度保存してください。'

/** スナップショットから条件へ写す値。保存済みの期間と vCenter だけを使う。 */
export function snapshotConditions(item: IncidentTimelineManualSnapshotListItem): {
  range: ResolvedRange
  vcenterId: string
} {
  return {
    range: { from: new Date(item.from).toISOString(), to: new Date(item.to).toISOString() },
    vcenterId: item.graph_context?.vcenter_id ?? item.build_request_payload.vcenter_id ?? '',
  }
}

/**
 * 手動スナップショットの一覧・保存・選択。折りたたみを開いたときに一覧を読む。
 * 保存は、表示中の条件を `view_request` として送り、サーバが保存時に集計した結果も保存する。
 * 選んだときだけ条件へ反映する（先頭を自動で選ぶと、URL の条件を上書きしてしまうため）。
 * 結果を持つもの（`has_result`）は詳細を取得して保存時点の結果を表示し、持たないもの・読めなかったものは
 * 保存した条件で再集計する。
 */
export function useTimelineSnapshots(params: {
  onError: (e: string | null) => void
  /** 画面の vCenter 条件。保存の `graph_context` に入れる。 */
  vcenterId: string
  /** 表示中の結果を取得した期間。無ければ保存できない。 */
  loadedRange: ResolvedRange | null
  /** 表示中の結果を取得したときに送った本文。そのまま `view_request` として保存する。 */
  loadedRequest: IncidentTimelineViewRequest | null
  /** 旧データ（条件が期間と vCenter だけ）を条件へ写して再集計する。 */
  applyConditions: (range: ResolvedRange, vcenterId: string) => void
  /** 保存した `view_request` の条件へ写して再集計する。 */
  applyViewRequest: (request: SavedIncidentTimelineViewRequest, options?: { notice?: string }) => void
  /** 利用者の意図の通し番号（条件が変わったかを見分ける）。 */
  getIntent: () => number
  /** 保存済みの結果をそのまま表示する。 */
  showSavedResult: (saved: Omit<SavedViewState, 'range'>, request: SavedIncidentTimelineViewRequest) => void
}) {
  const { onError, vcenterId, loadedRange, loadedRequest, applyConditions, applyViewRequest, showSavedResult, getIntent } = params
  const [open, setOpenState] = useState(false)
  const [items, setItems] = useState<IncidentTimelineManualSnapshotListItem[]>([])
  const [listLoaded, setListLoaded] = useState(false)
  /** 一覧の取得に失敗した（「読み込み中…」のままにしないため）。 */
  const [listFailed, setListFailed] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const selectedIdRef = useRef<string | null>(null)
  const [operatorNote, setOperatorNote] = useState('')
  const [saving, setSaving] = useState(false)

  const fetchItems = useCallback(async () => {
    try {
      const raw = await apiGet<unknown>('/api/incident-timeline/snapshots/manual?limit=20&offset=0')
      setItems(incidentTimelineManualSnapshotListResponseSchema.parse(raw).items)
      setListLoaded(true)
      setListFailed(false)
    } catch (e) {
      setListFailed(true)
      onError(snapshotErrorMessage(e, 'スナップショットの一覧'))
    }
  }, [onError])

  const setOpen = useCallback(
    (next: boolean) => {
      setOpenState(next)
      if (next && !listLoaded) void fetchItems()
    },
    [fetchItems, listLoaded],
  )

  const selectSeqRef = useRef(0)

  const select = useCallback(
    async (source: IncidentTimelineManualSnapshotListItem | string) => {
      const handoff = typeof source === 'string'
      const snapshotId = handoff ? source : source.snapshot_id
      if (handoff) onError(null)
      const seq = ++selectSeqRef.current
      const previousId = selectedIdRef.current
      setSelectedId(snapshotId)
      selectedIdRef.current = snapshotId
      const restoreSelection = () => {
        setSelectedId(previousId)
        selectedIdRef.current = previousId
      }
      if (!handoff && !source.has_result) {
        // 結果の無い旧データ: 保存した条件（view_request か、期間と vCenter）で再集計する
        const { range, vcenterId: id } = snapshotConditions(source)
        if (source.view_request) applyViewRequest(source.view_request)
        else applyConditions(range, id)
        return
      }
      const intent = getIntent()
      try {
        const detail = await getManualSnapshotDetail(snapshotId)
        // 続けて別のものを選んだ・取得中に条件を変えたなら、この結果は使わない
        if (seq !== selectSeqRef.current || getIntent() !== intent) {
          if (seq === selectSeqRef.current) restoreSelection()
          return
        }
        const { range, vcenterId: id } = snapshotConditions(handoff ? detail : source)
        const request: SavedIncidentTimelineViewRequest = detail.view_request ?? (handoff ? undefined : source.view_request) ?? {
          from: range.from,
          to: range.to,
          ...(id ? { vcenter_id: id } : {}),
        }
        if (handoff && !detail.has_result) {
          // 一覧で結果の無いスナップショットを選んだときと同じ条件を使う。
          if (detail.view_request) applyViewRequest(detail.view_request)
          else applyConditions(range, id)
        } else if (detail.has_result && detail.result) {
          showSavedResult(
            {
              snapshotId: detail.snapshot_id,
              note: detail.operator_note,
              savedAt: detail.created_at ?? detail.timestamp_utc,
              result: detail.result,
            },
            request,
          )
        } else {
          // 保存時のスキーマと合わず読めない結果。黙らず注記して、保存した条件で再集計する
          applyViewRequest(request, { notice: SAVED_RESULT_UNREADABLE_NOTICE })
        }
      } catch (e) {
        if (seq === selectSeqRef.current) {
          restoreSelection()
          if (getIntent() === intent) {
            onError(handoff && e instanceof ApiError && e.status === 404
              ? 'スナップショットを開けませんでした'
              : snapshotErrorMessage(e, 'スナップショットの詳細'))
          }
        }
      }
    },
    [applyConditions, applyViewRequest, showSavedResult, getIntent, onError],
  )

  const save = useCallback(async () => {
    const note = operatorNote.trim()
    if (note === '' || !loadedRange || !loadedRequest) return
    onError(null)
    setSaving(true)
    try {
      const buildRequestPayload = buildIncidentTimelineBuildRequestPayload({
        resolvedRange: loadedRange,
        options: {
          vcenterId,
          includePeriodMetricsCpu: false,
          includePeriodMetricsMemory: false,
          includePeriodMetricsDiskIo: false,
          includePeriodMetricsNetworkIo: false,
          metricThresholdCpuPct: DEFAULT_METRIC_THRESHOLD_CPU_PCT,
          metricThresholdMemoryPct: DEFAULT_METRIC_THRESHOLD_MEMORY_PCT,
        },
      })
      const tsIso = new Date().toISOString()
      const payload = incidentTimelineManualSnapshotCreateRequestSchema.parse({
        from: loadedRange.from,
        to: loadedRange.to,
        timestamp_utc: tsIso,
        operator_note: note,
        build_request_payload: buildRequestPayload,
        view_request: loadedRequest,
        graph_context: {
          marker_timestamp_utc: tsIso,
          ...(vcenterId.trim() !== '' ? { vcenter_id: vcenterId } : {}),
          captured_range: { from: loadedRange.from, to: loadedRange.to },
        },
      })
      const raw = await apiPost<unknown>('/api/incident-timeline/snapshots/manual', payload)
      incidentTimelineManualSnapshotCreateResponseSchema.parse(raw)
      await fetchItems()
      setOperatorNote('')
    } catch (e) {
      onError(e instanceof ApiError && e.status === 413 ? SNAPSHOT_TOO_LARGE_MESSAGE : toErrorMessage(e))
    } finally {
      setSaving(false)
    }
  }, [operatorNote, loadedRange, loadedRequest, onError, vcenterId, fetchItems])

  return { open, setOpen, items, listLoaded, listFailed, selectedId, select, operatorNote, setOperatorNote, saving, save }
}
