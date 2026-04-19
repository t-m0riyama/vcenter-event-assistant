import { z } from 'zod'
import { asArray } from '../utils/asArray'

/** イベント種別ガイド（API の `EventTypeGuideSnippet` に対応） */
export const eventTypeGuideSnippetSchema = z.object({
  general_meaning: z.string().nullable().optional(),
  typical_causes: z.string().nullable().optional(),
  remediation: z.string().nullable().optional(),
  action_required: z.boolean().optional().default(false),
})

export type EventTypeGuideSnippet = z.infer<typeof eventTypeGuideSnippetSchema>

export const eventRowSchema = z
  .object({
    id: z.number(),
    vcenter_id: z.string(),
    occurred_at: z.string(),
    event_type: z.string(),
    message: z.string(),
    severity: z.string().nullable(),
    notable_score: z.number(),
    notable_tags: z.array(z.string()).nullable().optional(),
    user_name: z.string().nullable().optional(),
    entity_name: z.string().nullable().optional(),
    entity_type: z.string().nullable().optional(),
    user_comment: z.string().nullable().optional(),
    type_guide: eventTypeGuideSnippetSchema.nullable().optional(),
  })
  .passthrough()

export type EventRow = z.infer<typeof eventRowSchema>

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

export const summarySchema = z
  .object({
    vcenter_count: z.number(),
    events_last_24h: z.number(),
    notable_events_last_24h: z.number(),
    top_notable_events: z.unknown(),
    high_cpu_hosts: z.unknown(),
    high_mem_hosts: z.unknown(),
    top_event_types_24h: z.unknown(),
  })
  .passthrough()

export type TopEventTypeRow = z.infer<typeof topEventTypeRowSchema>

export type Summary = {
  vcenter_count: number
  events_last_24h: number
  notable_events_last_24h: number
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

export const vcenterSchema = z
  .object({
    id: z.string(),
    name: z.string(),
    host: z.string(),
    port: z.number(),
    username: z.string(),
    is_enabled: z.boolean(),
    created_at: z.string(),
  })
  .passthrough()

export type VCenter = z.infer<typeof vcenterSchema>

export const appConfigSchema = z.object({
  event_retention_days: z.number(),
  metric_retention_days: z.number(),
  perf_sample_interval_seconds: z.number(),
})

export type AppConfig = z.infer<typeof appConfigSchema>

export const eventScoreRuleRowSchema = z.object({
  id: z.number(),
  event_type: z.string(),
  score_delta: z.number(),
})

export type EventScoreRuleRow = z.infer<typeof eventScoreRuleRowSchema>

export const eventScoreRuleListSchema = z.array(eventScoreRuleRowSchema)

export const eventTypeGuideRowSchema = z.object({
  id: z.number(),
  event_type: z.string(),
  general_meaning: z.string().nullable().optional(),
  typical_causes: z.string().nullable().optional(),
  remediation: z.string().nullable().optional(),
  action_required: z.boolean(),
})

export type EventTypeGuideRow = z.infer<typeof eventTypeGuideRowSchema>

export const eventTypeGuideListSchema = z.array(eventTypeGuideRowSchema)

/** エクスポート／インポート用の1行（DB の id は含めない） */
export const eventScoreRuleExportEntrySchema = z.object({
  event_type: z
    .string()
    .transform((s) => s.trim())
    .pipe(z.string().min(1).max(512)),
  score_delta: z.number().int().min(-10_000).max(10_000),
})

export type EventScoreRuleExportEntry = z.infer<typeof eventScoreRuleExportEntrySchema>

/** スコアルール JSON ファイル本体（`format` / `version` で識別） */
export const eventScoreRulesFileSchema = z
  .object({
    format: z.literal('vea-event-score-rules'),
    version: z.number().int().min(1),
    exportedAt: z.string().optional(),
    rules: z.array(eventScoreRuleExportEntrySchema),
  })
  .superRefine((data, ctx) => {
    const seen = new Set<string>()
    for (let i = 0; i < data.rules.length; i += 1) {
      const et = data.rules[i].event_type
      if (seen.has(et)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'rules 内に同一の event_type が重複しています',
          path: ['rules', i, 'event_type'],
        })
        return
      }
      seen.add(et)
    }
  })

export type EventScoreRulesFile = z.infer<typeof eventScoreRulesFileSchema>

/** `POST /api/event-score-rules/import` のレスポンス */
export const eventScoreRulesImportResponseSchema = z.object({
  rules_count: z.number(),
  events_updated: z.number(),
})

export type EventScoreRulesImportResponse = z.infer<typeof eventScoreRulesImportResponseSchema>

/**
 * 現在のルール一覧から、ファイル保存用のオブジェクトを組み立てる（検証済みの型を返す）。
 */
export function buildScoreRulesExportPayload(rows: readonly EventScoreRuleRow[]): EventScoreRulesFile {
  const rules: EventScoreRuleExportEntry[] = rows.map((r) =>
    eventScoreRuleExportEntrySchema.parse({
      event_type: r.event_type,
      score_delta: r.score_delta,
    }),
  )
  return eventScoreRulesFileSchema.parse({
    format: 'vea-event-score-rules',
    version: 1,
    exportedAt: new Date().toISOString(),
    rules,
  })
}

const _GUIDE_TEXT_MAX = 8000

/** イベント種別ガイド JSON の1行（DB の id は含めない） */
export const eventTypeGuideExportEntrySchema = z.object({
  event_type: z
    .string()
    .transform((s) => s.trim())
    .pipe(z.string().min(1).max(512)),
  general_meaning: z.union([z.string().max(_GUIDE_TEXT_MAX), z.null()]).optional(),
  typical_causes: z.union([z.string().max(_GUIDE_TEXT_MAX), z.null()]).optional(),
  remediation: z.union([z.string().max(_GUIDE_TEXT_MAX), z.null()]).optional(),
  action_required: z.boolean(),
})

export type EventTypeGuideExportEntry = z.infer<typeof eventTypeGuideExportEntrySchema>

/** イベント種別ガイド JSON ファイル本体 */
export const eventTypeGuidesFileSchema = z
  .object({
    format: z.literal('vea-event-type-guides'),
    version: z.number().int().min(1),
    exportedAt: z.string().optional(),
    guides: z.array(eventTypeGuideExportEntrySchema),
  })
  .superRefine((data, ctx) => {
    const seen = new Set<string>()
    for (let i = 0; i < data.guides.length; i++) {
      const et = data.guides[i].event_type
      if (seen.has(et)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'guides 内に同一の event_type が重複しています',
          path: ['guides', i, 'event_type'],
        })
        return
      }
      seen.add(et)
    }
  })

export type EventTypeGuidesFile = z.infer<typeof eventTypeGuidesFileSchema>

/** `POST /api/event-type-guides/import` のレスポンス */
export const eventTypeGuidesImportResponseSchema = z.object({
  guides_count: z.number(),
})

export type EventTypeGuidesImportResponse = z.infer<typeof eventTypeGuidesImportResponseSchema>

/**
 * 現在のガイド一覧から、ファイル保存用のオブジェクトを組み立てる（検証済みの型を返す）。
 */
export function buildEventTypeGuidesExportPayload(rows: readonly EventTypeGuideRow[]): EventTypeGuidesFile {
  const guides: EventTypeGuideExportEntry[] = rows.map((r) =>
    eventTypeGuideExportEntrySchema.parse({
      event_type: r.event_type,
      general_meaning: r.general_meaning ?? null,
      typical_causes: r.typical_causes ?? null,
      remediation: r.remediation ?? null,
      action_required: r.action_required,
    }),
  )
  return eventTypeGuidesFileSchema.parse({
    format: 'vea-event-type-guides',
    version: 1,
    exportedAt: new Date().toISOString(),
    guides,
  })
}

const eventListEnvelopeSchema = z.object({
  items: z.unknown().optional(),
  total: z.unknown().optional(),
})

/**
 * Accepts `{ items, total }` or a legacy JSON array so we never set `rows` to undefined (avoids render crash).
 *
 * `rawItemCount` is the number of elements in the API payload before validation. Chunked CSV export
 * must advance `offset` by this value, not by validated `items.length`, or a batch whose rows all
 * fail validation would stall pagination (`items.length === 0` while more rows exist on the server).
 */
export function normalizeEventListPayload(raw: unknown): {
  items: EventRow[]
  total: number
  rawItemCount: number
} {
  if (Array.isArray(raw)) {
    const rawItemCount = raw.length
    const items = raw.map((row) => eventRowSchema.safeParse(row)).flatMap((r) =>
      r.success ? [r.data] : [],
    )
    return { items, total: items.length, rawItemCount }
  }
  const env = eventListEnvelopeSchema.safeParse(raw)
  if (!env.success) {
    return { items: [], total: 0, rawItemCount: 0 }
  }
  const rawItems = asArray<unknown>(env.data.items)
  const rawItemCount = rawItems.length
  const items = rawItems
    .map((row) => eventRowSchema.safeParse(row))
    .flatMap((r) => (r.success ? [r.data] : []))
  const total =
    typeof env.data.total === 'number' && Number.isFinite(env.data.total)
      ? env.data.total
      : items.length
  return { items, total, rawItemCount }
}

/** 保存済みダイジェスト 1 件（API の `DigestRead` に対応） */
export const digestReadSchema = z.object({
  id: z.number(),
  period_start: z.string(),
  period_end: z.string(),
  kind: z.string(),
  body_markdown: z.string(),
  status: z.string(),
  error_message: z.string().nullable(),
  llm_model: z.string().nullable(),
  created_at: z.string(),
})

export type DigestRead = z.infer<typeof digestReadSchema>

export const digestListResponseSchema = z.object({
  items: z.array(digestReadSchema),
  total: z.number(),
})

export type DigestListResponse = z.infer<typeof digestListResponseSchema>

export function parseDigestListResponse(raw: unknown): DigestListResponse {
  return digestListResponseSchema.parse(raw)
}

export const chatMessageSchema = z.object({
  role: z.enum(['user', 'assistant']),
  content: z.string(),
  created_at: z.string().optional(),
  latency_ms: z.number().nullable().optional(),
  token_per_sec: z.number().nullable().optional(),
})

export type ChatMessage = z.infer<typeof chatMessageSchema>

/** チャット LLM 直前のコンテキスト統計（トークン切り詰めの確認用） */
export const chatLlmContextMetaSchema = z.object({
  json_truncated: z.boolean(),
  estimated_input_tokens: z.number(),
  max_input_tokens: z.number(),
  message_turns: z.number(),
})

export type ChatLlmContextMeta = z.infer<typeof chatLlmContextMetaSchema>

export const chatResponseSchema = z.object({
  assistant_content: z.string(),
  error: z.string().nullable(),
  llm_context: chatLlmContextMetaSchema.nullable().optional(),
  created_at: z.string().optional(),
  latency_ms: z.number().nullable().optional(),
  token_per_sec: z.number().nullable().optional(),
})

export type ChatResponse = z.infer<typeof chatResponseSchema>

export function parseChatResponse(raw: unknown): ChatResponse {
  return chatResponseSchema.parse(raw)
}

export const chatPreviewResponseSchema = z.object({
  context_block: z.string(),
  conversation: z.array(chatMessageSchema),
  llm_context: chatLlmContextMetaSchema.nullable().optional(),
})

export type ChatPreviewResponse = z.infer<typeof chatPreviewResponseSchema>

export function parseChatPreviewResponse(raw: unknown): ChatPreviewResponse {
  return chatPreviewResponseSchema.parse(raw)
}
