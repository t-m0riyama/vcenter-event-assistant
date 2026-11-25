import { z } from 'zod'
import { diagnosticRunSchema } from './diagnostics'

const uuid = z.guid()
const timestamp = z.iso.datetime({ offset: true, local: true })
const integer = z.number().int()
export const incidentStatusSchema = z.enum(['open', 'monitoring', 'resolved'])
export const incidentLevelSchema = z.enum(['critical', 'error', 'warning'])
const title = z.string().max(200).refine((value) => value.trim().length > 0)
const fields = {
  title,
  status: incidentStatusSchema,
  level: incidentLevelSchema.nullable(),
  assignee: z.string().refine((value) => Array.from(value).length <= 256).nullable(),
  summary: z.string().max(20_000),
  started_at: timestamp.nullable(),
}

const optionalFields = z.object(fields).partial().shape

export const timedIncidentSourceSchema = z.strictObject({
  id: integer,
  occurred_at: timestamp.nullish(),
  occurred_from: timestamp.nullish(),
  occurred_to: timestamp.nullish(),
}).refine((item) => item.occurred_at != null || (item.occurred_from != null && item.occurred_to != null))

const timedSources = timedIncidentSourceSchema.array().max(100)
const snapshotIds = uuid.array().max(100)
export const incidentTimedLinksRequestSchema = z.strictObject({ items: timedSources })
export const incidentSnapshotLinksRequestSchema = z.strictObject({ snapshot_ids: snapshotIds })
export const incidentCreateSchema = z.strictObject({
  ...optionalFields,
  title,
  events: timedSources.optional(),
  alerts: timedSources.optional(),
  snapshot_ids: snapshotIds.optional(),
})
export const incidentPatchSchema = z.strictObject({
  ...optionalFields,
  summary: fields.summary.nullish(),
  revision: uuid,
})
export const incidentEntryCreateSchema = z.strictObject({
  body: z.string().max(4000).refine((value) => value.trim().length > 0),
})

const incidentReadSchema = z.object({
  id: uuid,
  title: z.string(),
  status: incidentStatusSchema,
  level: fields.level,
  assignee: z.string().nullable(),
  started_at: fields.started_at,
  resolved_at: timestamp.nullable(),
  created_by: z.string(),
  updated_by: z.string(),
  created_at: timestamp,
  updated_at: timestamp,
  revision: uuid,
})
const incidentListItemSchema = incidentReadSchema.extend({
  event_count: integer,
  alert_count: integer,
  snapshot_count: integer,
})
export const incidentListSchema = z.object({ items: incidentListItemSchema.array(), total: integer })

export const incidentEntrySchema = z.object({
  id: integer,
  incident_id: uuid,
  kind: z.enum(['note', 'change', 'link', 'diagnostic']),
  body: z.string(),
  author: z.string(),
  created_at: timestamp,
  deleted_by: z.string().nullable(),
  deleted_at: timestamp.nullable(),
})

const copiedSourceSchema = z.object({
  id: integer,
  incident_id: uuid,
  vcenter_id: uuid.nullable(),
  vcenter_name: z.string().nullable(),
  entity_moid: z.string().nullable(),
  entity_name: z.string().nullable(),
  occurred_at: timestamp,
  added_by: z.string(),
  added_at: timestamp,
  source_exists: z.boolean(),
})
const eventLinkSchema = copiedSourceSchema.extend({
  event_id: integer,
  vcenter_id: uuid,
  vcenter_name: z.string(),
  collector_id: z.string(),
  vmware_key: integer,
  event_type: z.string(),
  severity: z.string().nullable(),
  notable_score: integer,
  entity_type: z.string().nullable(),
  user_name: z.string().nullable(),
  message: z.string(),
  user_comment: z.string().nullable(),
})
const alertLinkSchema = copiedSourceSchema.extend({
  alert_history_id: integer,
  rule_id: integer,
  rule_name: z.string().nullable(),
  rule_type: z.string(),
  alert_level: z.string(),
  state: z.string(),
  context_key: z.string(),
})
const snapshotLinkSchema = z.object({
  id: integer,
  snapshot_id: uuid,
  operator_note: z.string(),
  snapshot_kind: z.string(),
  from_time: timestamp,
  to_time: timestamp,
  created_at: timestamp,
  has_result: z.boolean(),
})
export const incidentDetailSchema = incidentReadSchema.extend({
  summary: z.string(),
  entries: incidentEntrySchema.array(),
  diagnostic_runs: diagnosticRunSchema.array().default([]),
  events: eventLinkSchema.array(),
  alerts: alertLinkSchema.array(),
  snapshots: snapshotLinkSchema.array(),
})

const linkResultSchema = z.object({
  id: z.union([integer, uuid]),
  result: z.enum(['added', 'already_linked', 'not_found', 'no_result', 'limit_exceeded']),
  link_id: integer.optional(),
})
export const incidentLinkResponseSchema = z.object({ results: linkResultSchema.array(), added: integer })
export const incidentCreateResponseSchema = z.object({
  incident: incidentDetailSchema,
  link_results: z.object({
    events: linkResultSchema.array(),
    alerts: linkResultSchema.array(),
    snapshots: linkResultSchema.array(),
  }),
})

export type IncidentStatus = z.infer<typeof incidentStatusSchema>
export type IncidentLevel = z.infer<typeof incidentLevelSchema>
export type IncidentDetail = z.infer<typeof incidentDetailSchema>
export type IncidentList = z.infer<typeof incidentListSchema>
export type IncidentCreate = z.infer<typeof incidentCreateSchema>
export type IncidentPatch = z.infer<typeof incidentPatchSchema>
export type TimedIncidentSource = z.infer<typeof timedIncidentSourceSchema>
export type IncidentLinkResult = z.infer<typeof linkResultSchema>
