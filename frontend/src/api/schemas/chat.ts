import { z } from 'zod'

import {
  isoOffsetDateTimeSchema,
  isoUtcDateTimeSchema,
  metricThresholdNullablePercentSchema,
} from './base'

export const chatMessageSchema = z.object({
  role: z.enum(['user', 'assistant']),
  content: z.string(),
  created_at: z.string().optional(),
  latency_ms: z.number().nullable().optional(),
  token_per_sec: z.number().nullable().optional(),
})

export type ChatMessage = z.infer<typeof chatMessageSchema>

export const chatRequestSchema = z.object({
  from: isoUtcDateTimeSchema,
  to: isoUtcDateTimeSchema,
  messages: z.array(chatMessageSchema).min(1),
  vcenter_id: z.string().uuid().optional(),
  top_notable_min_score: z.number().int().min(0).max(100).optional(),
  include_period_metrics_cpu: z.boolean().optional(),
  include_period_metrics_memory: z.boolean().optional(),
  include_period_metrics_disk_io: z.boolean().optional(),
  include_period_metrics_network_io: z.boolean().optional(),
  metric_threshold_cpu_pct: metricThresholdNullablePercentSchema,
  metric_threshold_memory_pct: metricThresholdNullablePercentSchema,
  metric_threshold_disk_pct: metricThresholdNullablePercentSchema,
  metric_threshold_network_pct: metricThresholdNullablePercentSchema,
})

export type ChatRequest = z.infer<typeof chatRequestSchema>

/** チャット LLM 直前のコンテキスト統計（トークン切り詰めの確認用） */
export const chatLlmContextMetaSchema = z.object({
  json_truncated: z.boolean(),
  estimated_input_tokens: z.number(),
  max_input_tokens: z.number(),
  message_turns: z.number(),
})

export type ChatLlmContextMeta = z.infer<typeof chatLlmContextMetaSchema>

/** 監査説明に用いるトリガー根拠の最小情報（backend TriggerEvidence と整合） */
export const triggerEvidenceSchema = z.object({
  trigger_type: z.string().min(1).max(128),
  summary: z.string().min(1).max(4000),
  source_id: z.string().nullable().optional(),
})

export type TriggerEvidence = z.infer<typeof triggerEvidenceSchema>

export const chatResponseSchema = z.object({
  assistant_content: z.string(),
  error: z.string().nullable(),
  llm_context: chatLlmContextMetaSchema.nullable().optional(),
  created_at: z.string().optional(),
  latency_ms: z.number().nullable().optional(),
  token_per_sec: z.number().nullable().optional(),
  trigger_evidence: triggerEvidenceSchema.nullable().optional(),
})

export type ChatResponse = z.infer<typeof chatResponseSchema>

export function parseChatResponse(raw: unknown): ChatResponse {
  return chatResponseSchema.parse(raw)
}

export const incidentTimelineEntrySchema = z.object({
  timestamp_utc: isoOffsetDateTimeSchema,
  kind: z.enum(['alert', 'event', 'metric']),
  title: z.string(),
})

export type IncidentTimelineEntry = z.infer<typeof incidentTimelineEntrySchema>

export const incidentTimelineColumnSchema = z
  .object({
    timestamp_utc: isoOffsetDateTimeSchema,
    bucket_start_utc: isoOffsetDateTimeSchema.nullable().optional(),
    bucket_end_utc: isoOffsetDateTimeSchema.nullable().optional(),
    items: z.array(incidentTimelineEntrySchema).optional().default([]),
    visible_items: z.array(incidentTimelineEntrySchema).optional(),
    hidden_count: z.number().int().min(0).optional(),
  })
  .transform((column) => {
    const visibleItems = column.visible_items ?? column.items
    const hiddenCount = column.hidden_count ?? Math.max(column.items.length - visibleItems.length, 0)
    return {
      ...column,
      visible_items: visibleItems,
      hidden_count: hiddenCount,
    }
  })

export type IncidentTimelineColumn = z.infer<typeof incidentTimelineColumnSchema>

export const incidentTimelineSchema = z.object({
  columns: z.array(incidentTimelineColumnSchema),
})

export type IncidentTimeline = z.infer<typeof incidentTimelineSchema>

export const incidentTimelineBuildRequestSchema = z
  .object({
    from: isoUtcDateTimeSchema,
    to: isoUtcDateTimeSchema,
    vcenter_id: z.string().uuid().nullable().optional(),
    top_notable_min_score: z.number().int().min(0).max(100).optional(),
    include_period_metrics_cpu: z.boolean().optional(),
    include_period_metrics_memory: z.boolean().optional(),
    include_period_metrics_disk_io: z.boolean().optional(),
    include_period_metrics_network_io: z.boolean().optional(),
    metric_threshold_cpu_pct: metricThresholdNullablePercentSchema,
    metric_threshold_memory_pct: metricThresholdNullablePercentSchema,
    metric_threshold_disk_pct: metricThresholdNullablePercentSchema,
    metric_threshold_network_pct: metricThresholdNullablePercentSchema,
    alert_top_n: z.number().int().min(1).max(20).optional(),
  })
  .strict()

export type IncidentTimelineBuildRequest = z.infer<typeof incidentTimelineBuildRequestSchema>

/** スナップショットに保存するグラフ再生用メタ（すべて任意） */
export const incidentTimelineGraphContextSchema = z
  .object({
    metric_key: z.string().max(512).optional(),
    chart_event_type: z.string().max(512).optional(),
    marker_timestamp_utc: isoUtcDateTimeSchema.optional(),
    vcenter_id: z.string().uuid().nullable().optional(),
    captured_range: z
      .object({
        from: isoUtcDateTimeSchema,
        to: isoUtcDateTimeSchema,
      })
      .strict()
      .optional(),
  })
  .strict()

export type IncidentTimelineGraphContext = z.infer<typeof incidentTimelineGraphContextSchema>

export function parseIncidentTimelineResponse(raw: unknown): IncidentTimeline {
  return incidentTimelineSchema.parse(raw)
}

export const incidentTimelineManualSnapshotCreateRequestSchema = z
  .object({
    from: isoUtcDateTimeSchema,
    to: isoUtcDateTimeSchema,
    timestamp_utc: isoUtcDateTimeSchema,
    operator_note: z.string().min(1).max(10_000),
    build_request_payload: incidentTimelineBuildRequestSchema.optional(),
    graph_context: incidentTimelineGraphContextSchema.optional(),
  })
  .strict()

export type IncidentTimelineManualSnapshotCreateRequest = z.infer<
  typeof incidentTimelineManualSnapshotCreateRequestSchema
>

export const incidentTimelineManualSnapshotCreateResponseSchema = z.object({
  snapshot_id: z.string().min(1),
  operator_note: z.string(),
  timestamp_utc: isoOffsetDateTimeSchema,
  build_request_payload: incidentTimelineBuildRequestSchema,
  snapshot_kind: z.enum(['manual', 'auto']).optional().default('manual'),
  trigger_id: z.string().optional().nullable(),
  graph_context: incidentTimelineGraphContextSchema.nullable().optional(),
})

export type IncidentTimelineManualSnapshotCreateResponse = z.infer<
  typeof incidentTimelineManualSnapshotCreateResponseSchema
>

export const incidentTimelineManualSnapshotListItemSchema = z.object({
  snapshot_id: z.string().min(1),
  from: isoOffsetDateTimeSchema,
  to: isoOffsetDateTimeSchema,
  operator_note: z.string(),
  timestamp_utc: isoOffsetDateTimeSchema,
  build_request_payload: incidentTimelineBuildRequestSchema,
  snapshot_kind: z.enum(['manual', 'auto']).optional().default('manual'),
  trigger_id: z.string().optional().nullable(),
  trigger_evidence: z.record(z.string(), z.unknown()).optional().nullable(),
  graph_context: incidentTimelineGraphContextSchema.nullable().optional(),
})

export type IncidentTimelineManualSnapshotListItem = z.infer<
  typeof incidentTimelineManualSnapshotListItemSchema
>

export const incidentTimelineManualSnapshotListResponseSchema = z.object({
  items: z.array(incidentTimelineManualSnapshotListItemSchema),
  total: z.number().int().min(0),
  limit: z.number().int().min(1),
  offset: z.number().int().min(0),
})

export type IncidentTimelineManualSnapshotListResponse = z.infer<
  typeof incidentTimelineManualSnapshotListResponseSchema
>

export const chatPreviewResponseSchema = z.object({
  context_block: z.string(),
  conversation: z.array(chatMessageSchema),
  llm_context: chatLlmContextMetaSchema.nullable().optional(),
  incident_timeline: incidentTimelineSchema.nullable().optional(),
})

export type ChatPreviewResponse = z.infer<typeof chatPreviewResponseSchema>

export function parseChatPreviewResponse(raw: unknown): ChatPreviewResponse {
  return chatPreviewResponseSchema.parse(raw)
}
