import { z } from 'zod'

import { asArray } from '../../utils/asArray'
import { eventRowSchema, type EventRow } from './events'
import { eventTypeGuideSnippetSchema } from './eventTypeGuides'

export const summaryHostMetricRowSchema = z.object({
  vcenter_id: z.string(),
  vcenter_label: z.string(),
  entity_name: z.string(),
  entity_moid: z.string(),
  value: z.number(),
  sampled_at: z.string(),
})

export type SummaryHostMetricRow = z.infer<typeof summaryHostMetricRowSchema>

export const topEventTypeRowSchema = z.object({
  event_type: z.string(),
  event_count: z.number(),
  max_notable_score: z.number(),
  type_guide: eventTypeGuideSnippetSchema.nullable().optional(),
})

export type TopEventTypeRow = z.infer<typeof topEventTypeRowSchema>

export const summarySchema = z
  .object({
    vcenter_count: z.number(),
    events_last_24h: z.number(),
    notable_events_last_24h: z.number(),
    // 旧サーバーはこのフィールドを返さないため optional（スパークライン非表示にフォールバック）
    events_last_24h_hourly: z.array(z.number()).optional(),
    notable_events_last_24h_hourly: z.array(z.number()).optional(),
    top_notable_events: z.unknown(),
    high_cpu_hosts: z.unknown(),
    high_mem_hosts: z.unknown(),
    top_event_types_24h: z.unknown(),
  })
  .passthrough()

export type Summary = {
  vcenter_count: number
  events_last_24h: number
  notable_events_last_24h: number
  events_last_24h_hourly: number[]
  notable_events_last_24h_hourly: number[]
  top_notable_events: EventRow[]
  high_cpu_hosts: SummaryHostMetricRow[]
  high_mem_hosts: SummaryHostMetricRow[]
  top_event_types_24h: TopEventTypeRow[]
}

export function parseSummary(raw: unknown): Summary {
  const base = summarySchema.parse(raw)
  return {
    vcenter_count: base.vcenter_count,
    events_last_24h: base.events_last_24h,
    notable_events_last_24h: base.notable_events_last_24h,
    events_last_24h_hourly: base.events_last_24h_hourly ?? [],
    notable_events_last_24h_hourly: base.notable_events_last_24h_hourly ?? [],
    top_notable_events: asArray<unknown>(base.top_notable_events)
      .map((row) => eventRowSchema.safeParse(row))
      .flatMap((r) => (r.success ? [r.data] : [])),
    high_cpu_hosts: asArray<unknown>(base.high_cpu_hosts)
      .map((h) => summaryHostMetricRowSchema.safeParse(h))
      .flatMap((r) => (r.success ? [r.data] : [])),
    high_mem_hosts: asArray<unknown>(base.high_mem_hosts)
      .map((h) => summaryHostMetricRowSchema.safeParse(h))
      .flatMap((r) => (r.success ? [r.data] : [])),
    top_event_types_24h: asArray<unknown>(base.top_event_types_24h)
      .map((r) => topEventTypeRowSchema.safeParse(r))
      .flatMap((x) => (x.success ? [x.data] : [])),
  }
}
