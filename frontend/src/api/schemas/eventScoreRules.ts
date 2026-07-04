import { z } from 'zod'

export const eventScoreRuleRowSchema = z.object({
  id: z.number(),
  event_type: z.string(),
  score_delta: z.number(),
})

export type EventScoreRuleRow = z.infer<typeof eventScoreRuleRowSchema>

export const eventScoreRuleListSchema = z.array(eventScoreRuleRowSchema)

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
