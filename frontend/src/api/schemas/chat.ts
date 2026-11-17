import { z } from 'zod'

import {
  isoOffsetDateTimeSchema,
  isoUtcDateTimeSchema,
  metricThresholdNullablePercentSchema,
} from './base'
import {
  incidentTimelineViewRequestSchema,
  incidentTimelineViewResponseSchema,
} from './incidentTimelineView'

export const chatMessageSchema = z.object({
  role: z.enum(['user', 'assistant']),
  content: z.string(),
  created_at: z.string().optional(),
  latency_ms: z.number().nullable().optional(),
  token_per_sec: z.number().nullable().optional(),
  /** クライアント側の送信トラッキング用（API には送らない） */
  client_request_id: z.string().optional(),
  /** そのターンに添付したファイル名（表示用。API には送らない） */
  attachment_names: z.array(z.string()).optional(),
})

/** 送信ターン限りの添付 1 件（backend ChatAttachment と整合） */
export const chatAttachmentSchema = z.object({
  kind: z.enum(['text', 'image']),
  filename: z.string().min(1).max(255),
  media_type: z.string().min(1).max(100),
  /** kind='text' のときの本文 */
  text: z.string().optional(),
  /** kind='image' のときの base64（データ URL 接頭辞なし） */
  data_base64: z.string().optional(),
  truncated: z.boolean().optional(),
})

export type ChatMessage = z.infer<typeof chatMessageSchema>

export const chatRequestSchema = z.object({
  from: isoUtcDateTimeSchema,
  to: isoUtcDateTimeSchema,
  messages: z.array(chatMessageSchema).min(1),
  /** この送信ターンにのみ添付するファイル（サーバーは保存しない） */
  attachments: z.array(chatAttachmentSchema).optional(),
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
  /** 偽のとき WEB 調査キャッシュの付記を抑止（既定 true・UI からは送らず API 直叩き向け） */
  include_research: z.boolean().optional(),
  /** 真のときこのメッセージの応答生成で LLM に WEB 検索ツールを許可（既定 false） */
  enable_web_search: z.boolean().optional(),
  /** WEB 検索の対象範囲（enable_web_search 真のとき有効。省略時サーバ既定） */
  web_search_scope: z.enum(['incidents', 'vsphere_ops', 'vmware_ecosystem']).optional(),
  /** WEB 検索の積極度（enable_web_search 真のとき有効。省略時サーバ既定） */
  web_search_aggressiveness: z.enum(['conservative', 'balanced', 'aggressive']).optional(),
})

export type ChatRequest = z.infer<typeof chatRequestSchema>

/** チャット LLM 直前のコンテキスト統計（トークン切り詰めの確認用） */
export const chatLlmContextMetaSchema = z.object({
  json_truncated: z.boolean(),
  estimated_input_tokens: z.number(),
  max_input_tokens: z.number(),
  message_turns: z.number(),
  attachment_count: z.number().optional(),
  attachment_text_chars: z.number().optional(),
  attachment_truncated: z.boolean().optional(),
  attachments_dropped_reason: z.string().nullable().optional(),
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
    // 画面からは送らない。保存済みのスナップショットに入っているので、受け取れるようにしておく。
    alert_top_n: z.number().int().min(1).max(20).optional(),
  })
  .strict()

export type IncidentTimelineBuildRequest = z.infer<typeof incidentTimelineBuildRequestSchema>

/**
 * サーバは未指定の項目を null で返す（`str | None`）。null は未指定（undefined）と同じ扱いにそろえる。
 * 使う側は `?? ''` などで読むので、型は optional のまま変わらない。
 */
function nullToUndefined<T extends z.ZodType>(schema: T) {
  return schema
    .nullish()
    .transform((value): z.output<T> | undefined => (value === null ? undefined : value))
}

/** スナップショットに保存するグラフ再生用メタ（すべて任意。応答では未指定が null で返る） */
export const incidentTimelineGraphContextSchema = z
  .object({
    metric_key: nullToUndefined(z.string().max(512)),
    chart_event_type: nullToUndefined(z.string().max(512)),
    marker_timestamp_utc: nullToUndefined(isoUtcDateTimeSchema),
    vcenter_id: z.string().uuid().nullable().optional(),
    captured_range: nullToUndefined(
      z
        .object({
          from: isoUtcDateTimeSchema,
          to: isoUtcDateTimeSchema,
        })
        .strict(),
    ),
  })
  .strict()

export type IncidentTimelineGraphContext = z.infer<typeof incidentTimelineGraphContextSchema>

export const incidentTimelineManualSnapshotCreateRequestSchema = z
  .object({
    from: isoUtcDateTimeSchema,
    to: isoUtcDateTimeSchema,
    timestamp_utc: isoUtcDateTimeSchema,
    operator_note: z.string().min(1).max(10_000),
    build_request_payload: incidentTimelineBuildRequestSchema.optional(),
    graph_context: incidentTimelineGraphContextSchema.optional(),
    /** 指定すると、サーバが保存時に集計して結果も保存する（結果はクライアントから送らない）。 */
    view_request: incidentTimelineViewRequestSchema.optional(),
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
  created_at: isoOffsetDateTimeSchema.nullable().optional(),
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
  /** 保存時点の結果を持つか（一覧には結果そのものは載らない）。古いサーバには無い。 */
  has_result: z.boolean().optional().default(false),
  /** サーバが保存した日時。`timestamp_utc` は利用者側の値なので、「保存した日時」にはこちらを使う。 */
  created_at: isoOffsetDateTimeSchema.nullable().optional(),
  /** 保存した view のリクエスト。読めない形のときは null として扱う。 */
  view_request: incidentTimelineViewRequestSchema.nullable().optional().catch(null),
})

export type IncidentTimelineManualSnapshotListItem = z.infer<
  typeof incidentTimelineManualSnapshotListItemSchema
>

/** 1 件の詳細。結果が無い・読めない形のときは null（`has_result` も false）。 */
export const incidentTimelineManualSnapshotDetailSchema = incidentTimelineManualSnapshotListItemSchema.extend({
  result: incidentTimelineViewResponseSchema.nullable().optional().catch(null),
})

export type IncidentTimelineManualSnapshotDetail = z.infer<typeof incidentTimelineManualSnapshotDetailSchema>

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
