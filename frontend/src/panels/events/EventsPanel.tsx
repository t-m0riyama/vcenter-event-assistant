import { useCallback, useMemo } from 'react'
import './EventsPanel.css'

import type { EventRow } from '../../api/schemas'
import {
  formatIsoInTimeZone,
} from '../../datetime/formatIsoInTimeZone'
import { ZonedRangeFields } from '../../datetime/ZonedRangeFields'
import { EVENT_PAGE_SIZES } from '../../events/constants'
import { EventTypeGuideBody } from '../../events/EventTypeGuideBody'
import { shouldHighlightEventRowForAction } from '../../events/eventTypeGuideHighlight'
import { summarizeEventTextFilters } from '../../events/eventFilterSummary'
import { useEventsPanelController } from '../../hooks/useEventsPanelController'
import { useIntervalWhenEnabled } from '../../hooks/useIntervalWhenEnabled'
import { useAutoRefreshPreferences } from '../../preferences/useAutoRefreshPreferences'
import { asArray } from '../../utils/asArray'

export function EventsPanel({ onError }: { onError: (e: string | null) => void }) {
  const c = useEventsPanelController(onError)
  const { load: reloadEvents } = c
  const { autoRefreshEnabled, autoRefreshIntervalMinutes } = useAutoRefreshPreferences()
  const intervalMs = useMemo(
    () => autoRefreshIntervalMinutes * 60_000,
    [autoRefreshIntervalMinutes],
  )
  const onAutoRefresh = useCallback(() => {
    void reloadEvents()
  }, [reloadEvents])
  useIntervalWhenEnabled(autoRefreshEnabled, intervalMs, onAutoRefresh)

  return (
    <div className="panel">
      <div className="toolbar">
        <label>
          最小スコア
          <input
            value={c.minScore}
            onChange={(e) => {
              c.setMinScore(e.target.value)
              c.setPage(1)
            }}
            placeholder="例: 40"
          />
        </label>
        <label>
          表示件数
          <select
            value={c.pageSize}
            onChange={(e) => {
              c.setPageSize(Number(e.target.value) as (typeof EVENT_PAGE_SIZES)[number])
              c.setPage(1)
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
            disabled={!c.canPrev}
            onClick={() => c.setPage((p) => Math.max(1, p - 1))}
          >
            前へ
          </button>
          <button
            type="button"
            className="btn"
            disabled={!c.canNext}
            onClick={() => c.setPage((p) => p + 1)}
          >
            次へ
          </button>
        </div>
        <span className="toolbar__meta">
          {c.total === 0 ? '全 0 件' : `全 ${c.total} 件中 ${c.start}–${c.end} 件を表示`}
        </span>
        <button
          type="button"
          className="btn btn--gray"
          disabled={c.exporting || c.total === 0}
          onClick={() => void c.downloadCsv()}
        >
          {c.exporting ? '出力中…' : 'CSV をダウンロード'}
        </button>
        <details className="toolbar__filters-details">
          <summary className="toolbar__filters-summary">
            <span className="toolbar__filters-summary__title">絞り込み条件</span>
            <span className="toolbar__filters-summary__preview">
              {summarizeEventTextFilters(
                c.filterEventType,
                c.filterSeverity,
                c.filterMessage,
                c.filterComment,
              )}
            </span>
          </summary>
          <p className="hint toolbar__filters-hint">
            表示期間は「設定 → 一般」のタイムゾーン上の壁時計です。未入力の端は制限なし。日付だけ選んだ場合は、開始は
            0:00・終了は 23:59 として扱います。クイックで直近の範囲を入れられます。
          </p>
          <ZonedRangeFields
            value={c.rangeParts}
            onChange={(next) => {
              c.setRangeParts(next)
              c.setPage(1)
            }}
          />
          <div className="toolbar__filters" aria-label="イベントの絞り込み（種別・重大度・メッセージ・コメント）">
            <label>
              種別（含む）
              <input
                value={c.filterEventType}
                onChange={(e) => {
                  c.setFilterEventType(e.target.value)
                  c.setPage(1)
                }}
                placeholder="部分一致"
                autoComplete="off"
              />
            </label>
            <label>
              重大度（含む）
              <input
                value={c.filterSeverity}
                onChange={(e) => {
                  c.setFilterSeverity(e.target.value)
                  c.setPage(1)
                }}
                placeholder="部分一致"
                autoComplete="off"
              />
            </label>
            <label>
              メッセージ（含む）
              <input
                value={c.filterMessage}
                onChange={(e) => {
                  c.setFilterMessage(e.target.value)
                  c.setPage(1)
                }}
                placeholder="部分一致"
                autoComplete="off"
              />
            </label>
            <label>
              コメント（含む）
              <input
                value={c.filterComment}
                onChange={(e) => {
                  c.setFilterComment(e.target.value)
                  c.setPage(1)
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
            <th>ガイド</th>
            <th>重大度</th>
            <th>スコア</th>
            <th>メッセージ</th>
            <th>運用メモ</th>
          </tr>
        </thead>
        <tbody>
          {asArray<EventRow>(c.rows).map((e) => (
            <tr
              key={e.id}
              className={
                shouldHighlightEventRowForAction(e.type_guide) ? 'event-row--action-required' : undefined
              }
            >
              <td>{formatIsoInTimeZone(e.occurred_at, c.timeZone)}</td>
              <td>{e.event_type}</td>
              <td className="event-type-guide-cell">
                {e.type_guide ? (
                  <div className="event-type-guide-cell__wrap">
                    <details className="event-type-guide-details">
                      <summary className="event-type-guide-summary">表示</summary>
                      <EventTypeGuideBody guide={e.type_guide} />
                    </details>
                    <div
                      className="event-type-guide-popover"
                      role="tooltip"
                      aria-hidden="true"
                    >
                      <EventTypeGuideBody guide={e.type_guide} />
                    </div>
                  </div>
                ) : (
                  '—'
                )}
              </td>
              <td>{e.severity ?? ''}</td>
              <td>{e.notable_score}</td>
              <td className="msg">{e.message}</td>
              <td className="event-comment-cell">
                {c.editingCommentId === e.id ? (
                  <div className="event-comment-edit">
                    <textarea
                      className="event-comment-textarea"
                      value={c.commentDraft}
                      onChange={(ev) => c.setCommentDraft(ev.target.value)}
                      rows={3}
                      maxLength={8000}
                      aria-label="運用メモ"
                    />
                    <div className="event-comment-actions">
                      <button
                        type="button"
                        className="btn btn--filled"
                        onClick={() => void c.saveComment(e.id)}
                      >
                        保存
                      </button>
                      <button type="button" className="btn" onClick={c.cancelCommentEdit}>
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
                      onClick={() => c.beginCommentEdit(e)}
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
