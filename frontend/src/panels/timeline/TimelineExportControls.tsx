import { useEffect, useId, useMemo, useRef, useState } from 'react'

import { ApiError, apiFetchBlob, GENERIC_API_ERROR } from '../../api'
import type { IncidentTimelineViewRequest } from '../../api/schemas'

type ExportSource = { snapshotId: string } | { request: IncidentTimelineViewRequest }
type ExportFormat = 'md' | 'zip'

export type TimelineExportActivity = {
  active: { ownerId: string; format: ExportFormat } | null
  claim: (ownerId: string, format: ExportFormat) => boolean
  release: () => void
}

const formats = [
  { value: 'md', label: 'Markdown' },
  { value: 'zip', label: 'ZIP' },
] as const

function exportErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.status) {
      case 404:
        return 'スナップショットが見つかりません。削除されたか、保持期間が過ぎた可能性があります。'
      case 409:
        if (error.errorCode === 'snapshot_result_missing') return error.message
        break
      case 413:
        return '出力する結果が大きすぎます。Markdown で出力するか、期間を狭めるか、種別を減らしてください。'
      case 422:
        return error.message === GENERIC_API_ERROR ? error.message : `出力条件を確認してください。${error.message}`
      case 429:
        return '短時間に操作が多すぎます。少し待ってから出力してください。'
      case 503:
        return 'サーバが混み合っています。しばらく待ってから出力してください。'
    }
  }
  return error instanceof Error ? error.message : '調査資料を出力できませんでした。'
}

export function TimelineExportControls({
  activity,
  source,
  sourceLabel,
  timeZone,
  unavailableReason,
}: {
  activity: TimelineExportActivity
  source: ExportSource | null
  sourceLabel?: string
  timeZone: string
  unavailableReason?: string
}) {
  const sourceKey = source && ('snapshotId' in source ? source.snapshotId : source.request)
  // 表示する結果が切り替わったら、前の出力の通知を消す。同じ結果を開き直した場合も表示しない。
  const sourceVersion = useMemo(() => ({ sourceKey }), [sourceKey])
  const [feedback, setFeedback] = useState<{ sourceVersion: typeof sourceVersion; message: string; failed: boolean } | null>(null)
  const status = feedback?.sourceVersion === sourceVersion ? feedback : null
  const pending = useRef<AbortController | null>(null)
  const ownerId = useId()
  const reasonId = `${ownerId}-reason`
  const statusId = `${ownerId}-status`
  const label = sourceLabel ? `${sourceLabel}の調査資料` : '調査資料'
  const exporting = activity.active?.ownerId === ownerId ? activity.active.format : null

  useEffect(() => () => pending.current?.abort(), [])

  const exportFile = async (format: ExportFormat) => {
    if (!source || !activity.claim(ownerId, format)) return
    const controller = new AbortController()
    const { signal } = controller
    pending.current = controller
    setFeedback({ sourceVersion, message: '出力しています…', failed: false })
    const query = new URLSearchParams({ format, time_zone: timeZone })
    try {
      const { blob, filename } = 'snapshotId' in source
        ? await apiFetchBlob(`/api/incident-timeline/snapshots/manual/${encodeURIComponent(source.snapshotId)}/export?${query}`, { signal })
        : await apiFetchBlob(`/api/incident-timeline/export?${query}`, { method: 'POST', body: source.request, signal })
      if (signal.aborted) return
      const url = URL.createObjectURL(blob)
      try {
        const link = document.createElement('a')
        link.href = url
        link.download = filename ?? `timeline.${format}`
        link.click()
      } finally {
        setTimeout(() => URL.revokeObjectURL(url), 0)
      }
      setFeedback({ sourceVersion, message: '調査資料のダウンロードを開始しました。', failed: false })
    } catch (error) {
      if (!signal.aborted) setFeedback({ sourceVersion, message: exportErrorMessage(error), failed: true })
    } finally {
      pending.current = null
      activity.release()
    }
  }

  return (
    <div
      className="timeline-export"
      role="group"
      aria-label={`${label}を出力`}
      aria-describedby={unavailableReason ? `${reasonId} ${statusId}` : statusId}
    >
      <span>調査資料を出力</span>
      {formats.map(({ value, label: formatLabel }) => (
        <button
          key={value}
          type="button"
          className="btn btn--gray"
          aria-label={`${label}を ${formatLabel} で出力`}
          disabled={!source || activity.active !== null}
          onClick={() => void exportFile(value)}
        >
          {exporting === value ? '出力中…' : formatLabel}
        </button>
      ))}
      {unavailableReason && <span id={reasonId} className="timeline-export__message">{unavailableReason}</span>}
      <span
        id={statusId}
        className={status?.failed ? 'timeline-export__message timeline-export__message--error' : 'timeline-export__message'}
        role="status"
        aria-label={`${label}の出力状況`}
      >
        {status?.message}
      </span>
    </div>
  )
}
