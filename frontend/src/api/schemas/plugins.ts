import { z } from 'zod'
import { isoOffsetDateTimeSchema } from './base'

export const collectorRunStatusSchema = z.object({
  vcenter_id: z.string(),
  vcenter_name: z.string(),
  status: z.enum(['idle', 'running', 'ok', 'failed']),
  collector_version: z.string(),
  last_started_at: isoOffsetDateTimeSchema.nullable(),
  last_success_at: isoOffsetDateTimeSchema.nullable(),
  last_failure_at: isoOffsetDateTimeSchema.nullable(),
  events_inserted: z.number().int(),
  metrics_inserted: z.number().int(),
  error: z.string().nullable(),
})

export const collectorStatusSchema = z.object({
  id: z.string(),
  display_name: z.string().nullable(),
  source: z.string(),
  status: z.enum(['enabled', 'disabled', 'failed']),
  error: z.string().nullable(),
  version: z.string().nullable(),
  api_version: z.number().int().nullable(),
  data_kinds: z.array(z.enum(['event', 'metric'])),
  interval_seconds: z.number().int().nullable(),
  timeout_seconds: z.number().nullable(),
  runs: z.array(collectorRunStatusSchema),
})

export const collectorStatusListSchema = z.object({
  generation: z.number().int(),
  collectors: z.array(collectorStatusSchema),
})

export type CollectorRunStatus = z.infer<typeof collectorRunStatusSchema>
export type CollectorStatus = z.infer<typeof collectorStatusSchema>
export type CollectorStatusList = z.infer<typeof collectorStatusListSchema>
