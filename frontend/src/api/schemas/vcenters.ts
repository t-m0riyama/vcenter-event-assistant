import { z } from 'zod'

export const vcenterSchema = z
  .object({
    id: z.string(),
    name: z.string(),
    host: z.string(),
    protocol: z.enum(['https', 'http']).default('https'),
    port: z.number(),
    username: z.string(),
    verify_ssl: z.boolean().default(false),
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
