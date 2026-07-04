import { escapeCsvField } from '../metrics/metricCsv'
import { formatMetricsDownloadTimestamp } from '../metrics/export/downloadChartSvg'

/** CSV エクスポート行（API ``EventRead`` 相当。vcenter は表示名）。 */
export type EventCsvRow = {
  id: number
  /** ユーザー選択 TZ で表示した発生時刻（``formatIsoInTimeZone``）。 */
  occurred_at: string
  vcenter_name: string
  event_type: string
  message: string
  severity: string | null
  user_name?: string | null
  entity_name?: string | null
  entity_type?: string | null
  notable_score: number
  notable_tags?: unknown[] | null
  user_comment?: string | null
}

const HEADER = [
  'id',
  'occurred_at',
  'vcenter_name',
  'event_type',
  'severity',
  'message',
  'user_name',
  'entity_name',
  'entity_type',
  'notable_score',
  'notable_tags',
  'user_comment',
] as const

function notableTagsToField(tags: unknown): string {
  if (tags == null) return ''
  try {
    return escapeCsvField(JSON.stringify(tags))
  } catch {
    return ''
  }
}

/** イベント行配列を CSV 文字列に変換する。 */
export function eventRowsToCsv(rows: EventCsvRow[]): string {
  const lines: string[] = [HEADER.join(',')]
  for (const e of rows) {
    lines.push(
      [
        String(e.id),
        escapeCsvField(String(e.occurred_at)),
        escapeCsvField(e.vcenter_name),
        escapeCsvField(e.event_type),
        escapeCsvField(e.severity ?? ''),
        escapeCsvField(e.message),
        escapeCsvField(e.user_name ?? ''),
        escapeCsvField(e.entity_name ?? ''),
        escapeCsvField(e.entity_type ?? ''),
        String(e.notable_score),
        notableTagsToField(e.notable_tags),
        escapeCsvField(e.user_comment ?? ''),
      ].join(','),
    )
  }
  return `${lines.join('\r\n')}\r\n`
}

/** イベント CSV をブラウザダウンロードする。 */
export function downloadEventListCsv(csv: string, filename: string): void {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  a.click()
  URL.revokeObjectURL(url)
}

/** イベント CSV のファイル名（``events-YYYYMMDD-HHmmss.csv``）を生成する。 */
export function buildEventExportFilename(d = new Date()): string {
  return `events-${formatMetricsDownloadTimestamp(d)}.csv`
}
