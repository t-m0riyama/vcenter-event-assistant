import { z } from 'zod'

import { asArray } from '../../utils/asArray'
import { eventTypeGuideSnippetSchema } from './eventTypeGuides'

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

const eventListEnvelopeSchema = z.object({
  items: z.unknown().optional(),
  total: z.unknown().optional(),
})

/**
 * Accepts `{ items, total }` or a legacy JSON array so we never set `rows` to undefined (avoids render crash).
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
