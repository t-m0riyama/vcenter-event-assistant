import { z } from 'zod'

import { eventPatternLevelSchema } from './eventPatterns'

/**
 * `POST /api/incident-timeline/view` の応答（`api/schemas/incident_timeline_view.py` に対応）。
 * 時刻は SQLite 由来で `Z` の無い文字列が返ることがあるため、検証は `z.string()` にとどめ、
 * 表示側で `parseApiUtcInstantMs` を使って UTC として解釈する。
 */
export const timelineSourceSchema = z.enum(['event', 'alert', 'metric', 'log'])
export type TimelineSource = z.infer<typeof timelineSourceSchema>

export const timelineLevelSchema = z.enum(['critical', 'error', 'warning', 'info'])
export type TimelineLevel = z.infer<typeof timelineLevelSchema>

export const timelineItemRefSchema = z.object({
  event_id: z.number().nullable().optional(),
  event_type: z.string().nullable().optional(),
  alert_history_id: z.number().nullable().optional(),
  alert_rule_id: z.number().nullable().optional(),
  alert_rule_name: z.string().nullable().optional(),
  alert_state: z.string().nullable().optional(),
  metric_key: z.string().nullable().optional(),
  entity_moid: z.string().nullable().optional(),
  log_id: z.number().nullable().optional(),
  // 以下はメトリクスの超過区間の行だけに入る構造化した値（古いサーバには無いので任意）
  threshold_pct: z.number().nullable().optional(),
  peak_value: z.number().nullable().optional(),
  peak_at_utc: z.string().nullable().optional(),
  sample_count: z.number().int().nullable().optional(),
  /** 期間の開始前から超過が続いているか。 */
  continues_from_before: z.boolean().nullable().optional(),
  /** 期間内の最後のサンプルの時点で、まだ超過していたか。`continues_from_before` と対になる。 */
  continues_after: z.boolean().nullable().optional(),
})
export type TimelineItemRef = z.infer<typeof timelineItemRefSchema>

export const timelineViewItemSchema = z.object({
  id: z.string(),
  kind: timelineSourceSchema,
  timestamp_utc: z.string(),
  end_utc: z.string().nullable().optional(),
  level: timelineLevelSchema,
  title: z.string(),
  detail: z.string().nullable().optional(),
  entity_name: z.string().nullable().optional(),
  entity_type: z.string().nullable().optional(),
  vcenter_id: z.string().nullable().optional(),
  vcenter_name: z.string().nullable().optional(),
  score: z.number().nullable().optional(),
  count: z.number().int().min(1).default(1),
  ref: timelineItemRefSchema.default({}),
})
export type TimelineViewItem = z.infer<typeof timelineViewItemSchema>

export const timelineOverviewBucketSchema = z.object({
  bucket_start_utc: z.string(),
  event_total: z.number().int().min(0),
  event_notable: z.number().int().min(0),
  alert: z.number().int().min(0),
  metric_breach: z.number().int().min(0),
  log_error: z.number().int().min(0),
})
export type TimelineOverviewBucket = z.infer<typeof timelineOverviewBucketSchema>

export const timelineTopEntitySchema = z.object({
  entity_name: z.string(),
  entity_moid: z.string().nullish(),
  entity_type: z.string().nullable().optional(),
  vcenter_id: z.string().nullable().optional(),
  vcenter_name: z.string().nullable().optional(),
  item_count: z.number().int(),
  first_seen_utc: z.string(),
})
export type TimelineTopEntity = z.infer<typeof timelineTopEntitySchema>

export const timelineNewEventTypeSchema = z.object({
  event_type: z.string(),
  count: z.number().int(),
  first_seen_utc: z.string(),
  max_score: z.number().int(),
})
export type TimelineNewEventType = z.infer<typeof timelineNewEventTypeSchema>

export const timelineDetectedPatternSchema = z.object({
  pattern_id: z.string(),
  title: z.string(),
  description: z.string(),
  level: eventPatternLevelSchema,
  vcenter_id: z.string(),
  vcenter_name: z.string().nullish(),
  entity_moid: z.string(),
  entity_name: z.string().nullish(),
  entity_type: z.string().nullish(),
  first_utc: z.string(),
  last_utc: z.string(),
  event_count: z.number().int().min(1),
  event_ids: z.array(z.number().int()).max(20),
})
export type TimelineDetectedPattern = z.infer<typeof timelineDetectedPatternSchema>

export const timelineHighlightsSchema = z.object({
  first_signal: timelineViewItemSchema.nullable().optional(),
  top_entities: z.array(timelineTopEntitySchema).default([]),
  new_event_types: z.array(timelineNewEventTypeSchema).default([]),
  detected_patterns: z.array(timelineDetectedPatternSchema).default([]),
  detected_patterns_total: z.number().int().min(0).default(0),
  omitted_patterns: z.array(z.string()).default([]),
})
export type TimelineHighlights = z.infer<typeof timelineHighlightsSchema>

/** 件数が多すぎて、一覧の行を省いた種別。`overview` の `log_error` は省いても入る。 */
export const timelineOmittedSourceSchema = z.object({
  source: z.string(),
  reason: z.string(),
})
export type TimelineOmittedSource = z.infer<typeof timelineOmittedSourceSchema>

export const incidentTimelineViewResponseSchema = z.object({
  from_utc: z.string(),
  to_utc: z.string(),
  anchor_utc: z.string().nullable().optional(),
  bucket_seconds: z.number().int().min(1),
  overview: z.array(timelineOverviewBucketSchema),
  items: z.array(timelineViewItemSchema),
  truncated: z.boolean(),
  total_items: z.number().int().min(0),
  highlights: timelineHighlightsSchema,
  omitted_sources: z.array(timelineOmittedSourceSchema).default([]),
})
export type IncidentTimelineViewResponse = z.infer<typeof incidentTimelineViewResponseSchema>

/** `POST /api/incident-timeline/view` の本文。 */
export type IncidentTimelineViewRequest = {
  from: string
  to: string
  anchor?: string
  vcenter_id?: string
  entity?: string
  entity_moid?: string | null
  min_score?: number
  sources?: TimelineSource[]
  metric_threshold_cpu_pct?: number
  metric_threshold_memory_pct?: number
  item_limit?: number
}

/**
 * スナップショットに保存された view のリクエスト（サーバが返す形）。サーバは未指定の項目を既定値で埋め、
 * `null` を返すことがあるので、`null` を許す。古い保存の形でも読めるよう、項目は緩く検証する。
 */
export const incidentTimelineViewRequestSchema = z.object({
  from: z.string(),
  to: z.string(),
  anchor: z.string().nullable().optional(),
  vcenter_id: z.string().nullable().optional(),
  entity: z.string().nullable().optional(),
  entity_moid: z.string().nullish(),
  min_score: z.number().nullish(),
  sources: z.array(timelineSourceSchema).nullish(),
  metric_threshold_cpu_pct: z.number().nullish(),
  metric_threshold_memory_pct: z.number().nullish(),
  metric_threshold_disk_pct: z.number().nullish(),
  metric_threshold_network_pct: z.number().nullish(),
  item_limit: z.number().nullish(),
})
export type SavedIncidentTimelineViewRequest = z.infer<typeof incidentTimelineViewRequestSchema>
