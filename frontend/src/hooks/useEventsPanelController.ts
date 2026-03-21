import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiGet, apiPatch } from '../api'
import type { EventRow, VCenter } from '../api/schemas'
import { normalizeEventListPayload } from '../api/schemas'
import { resolveEventApiRange } from '../datetime/graphRange'
import { parseApiUtcInstantMs } from '../datetime/formatIsoInTimeZone'
import { useTimeZone } from '../datetime/useTimeZone'
import {
  EMPTY_ZONED_RANGE_PARTS,
  zonedRangePartsToCombinedInputs,
  type ZonedRangeParts,
} from '../datetime/zonedRangeParts'
import { buildEventListSearchParams } from '../events/buildEventListQuery'
import {
  EVENT_EXPORT_CHUNK,
  EVENT_PAGE_SIZES,
} from '../events/constants'
import { eventRowToCsvRow } from '../events/eventRowToCsv'
import {
  buildEventExportFilename,
  downloadEventListCsv,
  eventRowsToCsv,
} from '../events/eventCsv'
import { asArray } from '../utils/asArray'
import { toErrorMessage } from '../utils/errors'

export type EventsPanelPageSize = (typeof EVENT_PAGE_SIZES)[number]

/**
 * イベント一覧の取得・ページング・CSV 出力・運用メモ編集の状態と副作用をまとめる。
 */
export function useEventsPanelController(onError: (e: string | null) => void) {
  const { timeZone } = useTimeZone()
  const [rows, setRows] = useState<EventRow[]>([])
  const [total, setTotal] = useState(0)
  const [minScore, setMinScore] = useState('')
  const [filterEventType, setFilterEventType] = useState('')
  const [filterSeverity, setFilterSeverity] = useState('')
  const [filterMessage, setFilterMessage] = useState('')
  const [filterComment, setFilterComment] = useState('')
  const [pageSize, setPageSize] = useState<EventsPanelPageSize>(50)
  const [page, setPage] = useState(1)
  const [editingCommentId, setEditingCommentId] = useState<number | null>(null)
  const [commentDraft, setCommentDraft] = useState('')
  const [exporting, setExporting] = useState(false)
  const [rangeParts, setRangeParts] = useState<ZonedRangeParts>(EMPTY_ZONED_RANGE_PARTS)
  const { rangeFromInput, rangeToInput } = useMemo(
    () => zonedRangePartsToCombinedInputs(rangeParts),
    [rangeParts],
  )

  const load = useCallback(async () => {
    onError(null)
    try {
      const range = resolveEventApiRange(rangeFromInput, rangeToInput, timeZone)
      if (!range.ok) {
        onError(range.message)
        return
      }
      const filters = {
        minScore,
        filterEventType,
        filterSeverity,
        filterMessage,
        filterComment,
      }
      const q = buildEventListSearchParams({
        limit: pageSize,
        offset: (page - 1) * pageSize,
        filters,
        range: { from: range.from, to: range.to },
      })
      const raw = await apiGet<unknown>(`/api/events?${q.toString()}`)
      const { items, total: nextTotal } = normalizeEventListPayload(raw)
      setRows(items)
      setTotal(nextTotal)
      const maxPage =
        nextTotal === 0 ? 1 : Math.max(1, Math.ceil(nextTotal / pageSize))
      setPage((p) => (p > maxPage ? maxPage : p))
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }, [
    onError,
    minScore,
    filterEventType,
    filterSeverity,
    filterMessage,
    filterComment,
    page,
    pageSize,
    rangeFromInput,
    rangeToInput,
    timeZone,
  ])

  useEffect(() => {
    void load()
  }, [load])

  const { start, end, safePage } = useMemo(() => {
    if (total === 0) return { start: 0, end: 0, safePage: 1 }
    const maxPage = Math.max(1, Math.ceil(total / pageSize))
    const sp = Math.min(page, maxPage)
    const s = (sp - 1) * pageSize + 1
    const e = Math.min(sp * pageSize, total)
    return { start: s, end: e, safePage: sp }
  }, [page, pageSize, total])

  const canPrev = safePage > 1
  const canNext = total > 0 && safePage * pageSize < total

  useEffect(() => {
    setEditingCommentId(null)
    setCommentDraft('')
  }, [
    page,
    pageSize,
    minScore,
    filterEventType,
    filterSeverity,
    filterMessage,
    filterComment,
    rangeParts,
  ])

  const beginCommentEdit = useCallback((e: EventRow) => {
    setEditingCommentId(e.id)
    setCommentDraft(e.user_comment ?? '')
  }, [])

  const cancelCommentEdit = useCallback(() => {
    setEditingCommentId(null)
    setCommentDraft('')
  }, [])

  const saveComment = useCallback(
    async (eventId: number) => {
      onError(null)
      try {
        const updated = await apiPatch<EventRow>(`/api/events/${eventId}`, {
          user_comment: commentDraft.trim() === '' ? null : commentDraft,
        })
        setRows((prev) => prev.map((r) => (r.id === eventId ? { ...r, ...updated } : r)))
        setEditingCommentId(null)
        setCommentDraft('')
      } catch (e) {
        onError(toErrorMessage(e))
      }
    },
    [commentDraft, onError],
  )

  const downloadCsv = useCallback(async () => {
    onError(null)
    setExporting(true)
    try {
      const range = resolveEventApiRange(rangeFromInput, rangeToInput, timeZone)
      if (!range.ok) {
        onError(range.message)
        return
      }
      const filters = {
        minScore,
        filterEventType,
        filterSeverity,
        filterMessage,
        filterComment,
      }
      const vcenters = await apiGet<unknown>('/api/vcenters')
      const vcenterList = asArray<VCenter>(vcenters)
      const nameById = new Map(vcenterList.map((v) => [v.id, v.name]))

      const all: EventRow[] = []
      let offset = 0
      let totalExpected = 0
      for (;;) {
        const q = buildEventListSearchParams({
          limit: EVENT_EXPORT_CHUNK,
          offset,
          filters,
          range: { from: range.from, to: range.to },
        })
        const raw = await apiGet<unknown>(`/api/events?${q.toString()}`)
        const { items, total, rawItemCount } = normalizeEventListPayload(raw)
        totalExpected = total
        all.push(...items)
        offset += rawItemCount
        if (rawItemCount === 0) break
        if (all.length >= totalExpected) break
      }
      all.sort(
        (a, b) =>
          parseApiUtcInstantMs(a.occurred_at) - parseApiUtcInstantMs(b.occurred_at),
      )
      const csv = eventRowsToCsv(
        all.map((e) =>
          eventRowToCsvRow(
            e,
            nameById.get(e.vcenter_id) ?? e.vcenter_id,
            timeZone,
          ),
        ),
      )
      downloadEventListCsv(csv, buildEventExportFilename())
    } catch (e) {
      onError(toErrorMessage(e))
    } finally {
      setExporting(false)
    }
  }, [
    onError,
    minScore,
    filterEventType,
    filterSeverity,
    filterMessage,
    filterComment,
    timeZone,
    rangeFromInput,
    rangeToInput,
  ])

  return {
    timeZone,
    rows,
    total,
    minScore,
    setMinScore,
    filterEventType,
    setFilterEventType,
    filterSeverity,
    setFilterSeverity,
    filterMessage,
    setFilterMessage,
    filterComment,
    setFilterComment,
    pageSize,
    setPageSize,
    page,
    setPage,
    rangeParts,
    setRangeParts,
    start,
    end,
    canPrev,
    canNext,
    exporting,
    downloadCsv,
    editingCommentId,
    commentDraft,
    setCommentDraft,
    beginCommentEdit,
    cancelCommentEdit,
    saveComment,
  }
}
