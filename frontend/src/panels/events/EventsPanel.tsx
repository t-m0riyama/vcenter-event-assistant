import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiGet, apiPatch } from '../../api'
import type { EventRow, VCenter } from '../../api/schemas'
import { normalizeEventListPayload } from '../../api/schemas'
import {
  formatIsoInTimeZone,
  parseApiUtcInstantMs,
} from '../../datetime/formatIsoInTimeZone'
import { useTimeZone } from '../../datetime/useTimeZone'
import { ZonedRangeFields } from '../../datetime/ZonedRangeFields'
import { resolveEventApiRange } from '../../datetime/graphRange'
import {
  EMPTY_ZONED_RANGE_PARTS,
  zonedRangePartsToCombinedInputs,
  type ZonedRangeParts,
} from '../../datetime/zonedRangeParts'
import {
  EVENT_EXPORT_CHUNK,
  EVENT_PAGE_SIZES,
} from '../../events/constants'
import { summarizeEventTextFilters } from '../../events/eventFilterSummary'
import { eventRowToCsvRow } from '../../events/eventRowToCsv'
import {
  buildEventExportFilename,
  downloadEventListCsv,
  eventRowsToCsv,
} from '../../events/eventCsv'
import { asArray } from '../../utils/asArray'
import { toErrorMessage } from '../../utils/errors'

export function EventsPanel({ onError }: { onError: (e: string | null) => void }) {
  const { timeZone } = useTimeZone()
  const [rows, setRows] = useState<EventRow[]>([])
  const [total, setTotal] = useState(0)
  const [minScore, setMinScore] = useState('')
  const [filterEventType, setFilterEventType] = useState('')
  const [filterSeverity, setFilterSeverity] = useState('')
  const [filterMessage, setFilterMessage] = useState('')
  const [filterComment, setFilterComment] = useState('')
  const [pageSize, setPageSize] = useState<(typeof EVENT_PAGE_SIZES)[number]>(50)
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
      const q = new URLSearchParams({
        limit: String(pageSize),
        offset: String((page - 1) * pageSize),
      })
      if (minScore) q.set('min_score', minScore)
      const et = filterEventType.trim()
      if (et) q.set('event_type_contains', et)
      const sv = filterSeverity.trim()
      if (sv) q.set('severity_contains', sv)
      const msg = filterMessage.trim()
      if (msg) q.set('message_contains', msg)
      const cm = filterComment.trim()
      if (cm) q.set('comment_contains', cm)
      if (range.from) q.set('from', range.from)
      if (range.to) q.set('to', range.to)
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

  const beginCommentEdit = (e: EventRow) => {
    setEditingCommentId(e.id)
    setCommentDraft(e.user_comment ?? '')
  }

  const cancelCommentEdit = () => {
    setEditingCommentId(null)
    setCommentDraft('')
  }

  const saveComment = async (eventId: number) => {
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
  }

  const downloadCsv = useCallback(async () => {
    onError(null)
    setExporting(true)
    try {
      const range = resolveEventApiRange(rangeFromInput, rangeToInput, timeZone)
      if (!range.ok) {
        onError(range.message)
        return
      }
      const vcenters = await apiGet<unknown>('/api/vcenters')
      const vcenterList = asArray<VCenter>(vcenters)
      const nameById = new Map(vcenterList.map((v) => [v.id, v.name]))

      const all: EventRow[] = []
      let offset = 0
      let totalExpected = 0
      for (;;) {
        const q = new URLSearchParams({
          limit: String(EVENT_EXPORT_CHUNK),
          offset: String(offset),
        })
        if (minScore) q.set('min_score', minScore)
        const et = filterEventType.trim()
        if (et) q.set('event_type_contains', et)
        const sv = filterSeverity.trim()
        if (sv) q.set('severity_contains', sv)
        const msg = filterMessage.trim()
        if (msg) q.set('message_contains', msg)
        const cm = filterComment.trim()
        if (cm) q.set('comment_contains', cm)
        if (range.from) q.set('from', range.from)
        if (range.to) q.set('to', range.to)
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

  return (
    <div className="panel">
      <div className="toolbar">
        <label>
          最小スコア
          <input
            value={minScore}
            onChange={(e) => {
              setMinScore(e.target.value)
              setPage(1)
            }}
            placeholder="例: 40"
          />
        </label>
        <label>
          表示件数
          <select
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value) as (typeof EVENT_PAGE_SIZES)[number])
              setPage(1)
            }}
          >
            {EVENT_PAGE_SIZES.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <div className="toolbar__pagination">
          <button
            type="button"
            className="btn"
            disabled={!canPrev}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            前へ
          </button>
          <button
            type="button"
            className="btn"
            disabled={!canNext}
            onClick={() => setPage((p) => p + 1)}
          >
            次へ
          </button>
        </div>
        <span className="toolbar__meta">
          {total === 0 ? '全 0 件' : `全 ${total} 件中 ${start}–${end} 件を表示`}
        </span>
        <button
          type="button"
          className="btn btn--gray"
          disabled={exporting || total === 0}
          onClick={() => void downloadCsv()}
        >
          {exporting ? '出力中…' : 'CSV をダウンロード'}
        </button>
        <details className="toolbar__filters-details">
          <summary className="toolbar__filters-summary">
            <span className="toolbar__filters-summary__title">絞り込み条件</span>
            <span className="toolbar__filters-summary__preview">
              {summarizeEventTextFilters(
                filterEventType,
                filterSeverity,
                filterMessage,
                filterComment,
              )}
            </span>
          </summary>
          <p className="hint toolbar__filters-hint">
            表示期間は「設定 → 一般」のタイムゾーン上の壁時計です。未入力の端は制限なし。日付だけ選んだ場合は、開始は
            0:00・終了は 23:59 として扱います。クイックで直近の範囲を入れられます。
          </p>
          <ZonedRangeFields
            value={rangeParts}
            onChange={(next) => {
              setRangeParts(next)
              setPage(1)
            }}
          />
          <div className="toolbar__filters" aria-label="イベントの絞り込み（種別・重大度・メッセージ・コメント）">
            <label>
              種別（含む）
              <input
                value={filterEventType}
                onChange={(e) => {
                  setFilterEventType(e.target.value)
                  setPage(1)
                }}
                placeholder="部分一致"
                autoComplete="off"
              />
            </label>
            <label>
              重大度（含む）
              <input
                value={filterSeverity}
                onChange={(e) => {
                  setFilterSeverity(e.target.value)
                  setPage(1)
                }}
                placeholder="部分一致"
                autoComplete="off"
              />
            </label>
            <label>
              メッセージ（含む）
              <input
                value={filterMessage}
                onChange={(e) => {
                  setFilterMessage(e.target.value)
                  setPage(1)
                }}
                placeholder="部分一致"
                autoComplete="off"
              />
            </label>
            <label>
              コメント（含む）
              <input
                value={filterComment}
                onChange={(e) => {
                  setFilterComment(e.target.value)
                  setPage(1)
                }}
                placeholder="部分一致"
                autoComplete="off"
              />
            </label>
          </div>
        </details>
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>時刻</th>
            <th>種別</th>
            <th>重大度</th>
            <th>スコア</th>
            <th>メッセージ</th>
            <th>運用メモ</th>
          </tr>
        </thead>
        <tbody>
          {asArray<EventRow>(rows).map((e) => (
            <tr key={e.id}>
              <td>{formatIsoInTimeZone(e.occurred_at, timeZone)}</td>
              <td>{e.event_type}</td>
              <td>{e.severity ?? ''}</td>
              <td>{e.notable_score}</td>
              <td className="msg">{e.message}</td>
              <td className="event-comment-cell">
                {editingCommentId === e.id ? (
                  <div className="event-comment-edit">
                    <textarea
                      className="event-comment-textarea"
                      value={commentDraft}
                      onChange={(ev) => setCommentDraft(ev.target.value)}
                      rows={3}
                      maxLength={8000}
                      aria-label="運用メモ"
                    />
                    <div className="event-comment-actions">
                      <button
                        type="button"
                        className="btn btn--filled"
                        onClick={() => void saveComment(e.id)}
                      >
                        保存
                      </button>
                      <button type="button" className="btn" onClick={cancelCommentEdit}>
                        キャンセル
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="event-comment-view">
                    <span className="event-comment-preview">
                      {e.user_comment?.trim() ? e.user_comment : '—'}
                    </span>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => beginCommentEdit(e)}
                    >
                      編集
                    </button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
