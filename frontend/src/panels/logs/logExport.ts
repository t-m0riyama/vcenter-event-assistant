import { z } from 'zod'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { escapeCsvField } from '../../metrics/metricCsv'
import { formatMetricsDownloadTimestamp } from '../../metrics/export/downloadChartSvg'
export { downloadEventListCsv as downloadLogListCsv } from '../../events/eventCsv'

export const logSchema = z.object({
  id: z.number(), vcenter_id: z.string(), source_id: z.string(), host: z.string(), log_kind: z.string(),
  file_generation: z.string(), byte_offset: z.number(), occurred_at: z.string().nullable(),
  collected_at: z.string(), effective_at: z.string(), severity: z.string().nullable(), message: z.string(),
})
export const logPageSchema = z.object({ items: z.array(logSchema), total: z.number().int().nonnegative() })
export type LogRow = z.infer<typeof logSchema>
export type LogFilters = {
  vcenter_id: string
  source_id: string
  log_kind: string
  severity: string
  message_contains: string
  from: string | undefined
  to: string | undefined
}

export function buildLogListSearchParams(filters: LogFilters, limit: number, offset: number): URLSearchParams {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value)
  }
  return params
}

export async function fetchAllLogsForExport(
  fetchPage: (params: URLSearchParams) => Promise<unknown>,
  filters: LogFilters,
): Promise<LogRow[]> {
  const all: LogRow[] = []
  for (;;) {
    const { items, total } = logPageSchema.parse(await fetchPage(buildLogListSearchParams(filters, 200, all.length)))
    all.push(...items)
    if (items.length === 0 || all.length >= total) return all
  }
}

const HEADER = [
  'id', 'vcenter_id', 'vcenter_name', 'source_id', 'host', 'log_kind',
  'effective_at', 'occurred_at', 'collected_at', 'severity', 'message', 'file_generation', 'byte_offset',
] as const

export function logRowsToCsv(rows: LogRow[], vcenterNames: ReadonlyMap<string, string>, timeZone: string): string {
  const lines = [HEADER.join(',')]
  for (const row of rows) {
    const fields = {
      ...row,
      vcenter_name: vcenterNames.get(row.vcenter_id) ?? row.vcenter_id,
      effective_at: formatIsoInTimeZone(row.effective_at, timeZone),
      occurred_at: row.occurred_at === null ? '' : formatIsoInTimeZone(row.occurred_at, timeZone),
      collected_at: formatIsoInTimeZone(row.collected_at, timeZone),
    }
    lines.push(HEADER.map((key) => escapeCsvField(String(fields[key] ?? ''))).join(','))
  }
  return `${lines.join('\r\n')}\r\n`
}

export function buildLogExportFilename(date = new Date()): string {
  return `logs-${formatMetricsDownloadTimestamp(date)}.csv`
}
