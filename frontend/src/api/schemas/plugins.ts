import { z } from 'zod'
import { isoOffsetDateTimeSchema } from './base'

export const collectorRunStatusSchema = z.object({
  vcenter_id: z.string(),
  vcenter_name: z.string(),
  status: z.enum(['idle', 'running', 'ok', 'failed']),
  collector_version: z.string(),
  last_started_at: isoOffsetDateTimeSchema.nullable(),
  last_success_at: isoOffsetDateTimeSchema.nullable(),
  last_failure_at: isoOffsetDateTimeSchema.nullable(),
  events_inserted: z.number().int(),
  metrics_inserted: z.number().int(),
  error: z.string().nullable(),
})

export const collectorStatusSchema = z.object({
  id: z.string(),
  display_name: z.string().nullable(),
  source: z.string(),
  status: z.enum(['enabled', 'disabled', 'failed']),
  error: z.string().nullable(),
  version: z.string().nullable(),
  api_version: z.number().int().nullable(),
  data_kinds: z.array(z.enum(['event', 'metric'])),
  interval_seconds: z.number().int().nullable(),
  timeout_seconds: z.number().nullable(),
  // 環境変数で固定され、DB 設定より優先されるため編集できない共通フィールド。
  env_locked_fields: z.array(z.string()).default([]),
  runs: z.array(collectorRunStatusSchema),
})

export const collectorStatusListSchema = z.object({
  generation: z.number().int(),
  management_enabled: z.boolean().default(false),
  reload_required: z.boolean().default(false),
  collectors: z.array(collectorStatusSchema),
})

export const collectorReloadSchema = z.object({
  generation: z.number().int(),
  jobs_added: z.array(z.string()),
  jobs_removed: z.array(z.string()),
  jobs_rescheduled: z.array(z.string()),
  collectors: z.array(collectorStatusSchema),
})

export const installedPluginSchema = z.object({
  distribution: z.string(),
  version: z.string(),
  source: z.enum(['upload', 'index', '']),
  origin: z.string(),
  status: z.enum(['installing', 'installed', 'failed']),
  error: z.string().nullable(),
  installed_at: isoOffsetDateTimeSchema,
})

export const installedPluginListSchema = z.object({
  management_enabled: z.boolean(),
  index_install_enabled: z.boolean(),
  plugins: z.array(installedPluginSchema),
})

export type CollectorRunStatus = z.infer<typeof collectorRunStatusSchema>
export type CollectorStatus = z.infer<typeof collectorStatusSchema>
export type CollectorStatusList = z.infer<typeof collectorStatusListSchema>
export type CollectorReload = z.infer<typeof collectorReloadSchema>
export type InstalledPlugin = z.infer<typeof installedPluginSchema>
export type InstalledPluginList = z.infer<typeof installedPluginListSchema>
