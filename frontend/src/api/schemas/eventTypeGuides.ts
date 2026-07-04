import { z } from 'zod'

/** イベント種別ガイド（API の `EventTypeGuideSnippet` に対応） */
export const eventTypeGuideSnippetSchema = z.object({
  general_meaning: z.string().nullable().optional(),
  typical_causes: z.string().nullable().optional(),
  remediation: z.string().nullable().optional(),
  action_required: z.boolean().optional().default(false),
})

export type EventTypeGuideSnippet = z.infer<typeof eventTypeGuideSnippetSchema>

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
    for (let i = 0; i < data.guides.length; i += 1) {
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
