import { z } from 'zod'

const logPatternSummarySchema = z.object({
  vcenter_id: z.string(),
  vcenter_name: z.string(),
  pattern_key: z.string(),
  log_kind: z.string(),
  template: z.string(),
  count: z.number().int().min(1),
  first_utc: z.string(),
  max_severity_rank: z.number().int().min(0),
  first_seen_at: z.string(),
})

const logPatternSchema = logPatternSummarySchema.extend({ last_utc: z.string() })
export type LogPattern = z.infer<typeof logPatternSchema>

export const logPatternsResponseSchema = z.object({
  items: z.array(logPatternSchema),
  total: z.number().int().min(0),
  truncated: z.boolean(),
  pending_count: z.number().int().min(0),
})
export type LogPatternsResponse = z.infer<typeof logPatternsResponseSchema>

export const timelineNewLogPatternSchema = logPatternSummarySchema.extend({
  hosts: z.array(z.string()),
  warning_first_seen_at: z.string(),
})
export type TimelineNewLogPattern = z.infer<typeof timelineNewLogPatternSchema>
