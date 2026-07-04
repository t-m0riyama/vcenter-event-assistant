import { z } from 'zod'

export const alertRuleConfigSchema = z.record(z.string(), z.unknown())

export const alertRuleRowSchema = z.object({
  id: z.number(),
  name: z.string(),
  rule_type: z.enum(['event_score', 'metric_threshold']),
  is_enabled: z.boolean(),
  alert_level: z.enum(['critical', 'error', 'warning']),
  config: alertRuleConfigSchema,
  created_at: z.string(),
})

export type AlertRuleRow = z.infer<typeof alertRuleRowSchema>

/** エクスポート／インポート用の1行（DB の id は含めない） */
export const alertRuleExportEntrySchema = z.object({
  name: z
    .string()
    .transform((s) => s.trim())
    .pipe(z.string().min(1).max(255)),
  rule_type: z.enum(['event_score', 'metric_threshold']),
  is_enabled: z.boolean(),
  alert_level: z.enum(['critical', 'error', 'warning']),
  config: alertRuleConfigSchema,
})

export type AlertRuleExportEntry = z.infer<typeof alertRuleExportEntrySchema>

/** アラートルール JSON ファイル本体 */
export const alertRulesFileSchema = z
  .object({
    format: z.literal('vea-alert-rules'),
    version: z.number().int().min(1),
    exportedAt: z.string().optional(),
    rules: z.array(alertRuleExportEntrySchema),
  })
  .superRefine((data, ctx) => {
    const seen = new Set<string>()
    for (let i = 0; i < data.rules.length; i += 1) {
      const ruleName = data.rules[i].name
      if (seen.has(ruleName)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'rules 内に同一の name が重複しています',
          path: ['rules', i, 'name'],
        })
        return
      }
      seen.add(ruleName)
    }
  })

export type AlertRulesFile = z.infer<typeof alertRulesFileSchema>

/** `POST /api/alerts/rules/import` のレスポンス */
export const alertRulesImportResponseSchema = z.object({
  rules_count: z.number(),
})

export type AlertRulesImportResponse = z.infer<typeof alertRulesImportResponseSchema>

/**
 * 現在のルール一覧から、アラートルールのファイル保存用オブジェクトを組み立てる。
 */
export function buildAlertRulesExportPayload(rows: readonly AlertRuleRow[]): AlertRulesFile {
  const rules: AlertRuleExportEntry[] = rows.map((r) =>
    alertRuleExportEntrySchema.parse({
      name: r.name,
      rule_type: r.rule_type,
      is_enabled: r.is_enabled,
      alert_level: r.alert_level,
      config: r.config,
    }),
  )
  return alertRulesFileSchema.parse({
    format: 'vea-alert-rules',
    version: 1,
    exportedAt: new Date().toISOString(),
    rules,
  })
}
