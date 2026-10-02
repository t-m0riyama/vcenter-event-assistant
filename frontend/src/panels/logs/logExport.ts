import { z } from 'zod'
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

/** Capture only search conditions and the selected zone, without list pagination. */
export function buildLogExportUrl(filters: LogFilters, timeZone: string): string {
  const params = new URLSearchParams({ time_zone: timeZone })
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value)
  }
  return `/api/logs/export.csv?${params}`
}

/** Hand the response directly to the browser; never buffer the file in JS. */
export function downloadLogCsv(url: string): void {
  const link = document.createElement('a')
  link.href = url
  link.download = ''
  // An HTTP error can be shown without replacing the application page.
  link.target = '_blank'
  link.rel = 'noopener'
  document.body.appendChild(link)
  try {
    link.click()
  } finally {
    link.remove()
  }
}
