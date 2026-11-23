import { z } from 'zod'

import { isoOffsetDateTimeSchema } from './base'

const inventoryTargetSchema = z.object({
  moid: z.string(),
  entity_type: z.string().nullable(),
  name: z.string(),
})

const countSchema = z.number().int().nonnegative()
const observationSchema = isoOffsetDateTimeSchema.nullable()

export const inventoryImpactResponseSchema = z.object({
  target: inventoryTargetSchema,
  at: isoOffsetDateTimeSchema,
  status: z.enum(['unsupported_type', 'not_recorded', 'unknown_target', 'absent_at_time', 'stale', 'ok']),
  recorded_since: observationSchema,
  last_success_at: observationSchema,
  observed_before: observationSchema,
  observed_after: observationSchema,
  groups: z.array(z.object({
    relation: z.enum(['cluster', 'hosts', 'vms', 'datastores', 'networks']),
    items: z.array(inventoryTargetSchema.extend({ removed: z.boolean() })),
    total: countSchema,
  })),
  changes: z.object({
    items: z.array(z.object({
      kind: z.string(),
      other: inventoryTargetSchema,
      at: isoOffsetDateTimeSchema,
      action: z.enum(['opened', 'closed']),
    })),
    total: countSchema,
  }).nullish(),
})

const inventoryVCenterStatusSchema = z.object({
  vcenter_id: z.guid(),
  vcenter_name: z.string(),
  is_enabled: z.boolean(),
  first_success_at: observationSchema,
  last_started_at: observationSchema,
  last_success_at: observationSchema,
  last_failure_at: observationSchema,
  last_error: z.string().nullable(),
  last_warning: z.string().nullable(),
  last_warning_at: observationSchema,
  object_count: countSchema.nullable(),
  relation_count: countSchema.nullable(),
})

export const inventoryStatusResponseSchema = z.object({
  enabled: z.boolean(),
  interval_seconds: z.number().int(),
  timeout_seconds: z.number().int(),
  vcenters: z.array(inventoryVCenterStatusSchema),
})

export type InventoryImpactResponse = z.infer<typeof inventoryImpactResponseSchema>
export type InventoryVCenterStatus = z.infer<typeof inventoryVCenterStatusSchema>
export type InventoryStatusResponse = z.infer<typeof inventoryStatusResponseSchema>
