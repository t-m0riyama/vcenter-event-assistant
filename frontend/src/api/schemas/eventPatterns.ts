import { z } from 'zod'

export const eventPatternLevelSchema = z.enum(['critical', 'error', 'warning'])

export const eventPatternSchema = z.object({
  id: z.string(),
  title: z.string(),
  description: z.string(),
  level: eventPatternLevelSchema,
  kind: z.enum(['repeat', 'sequence', 'occurrence']),
  steps: z.array(z.object({ event_types: z.array(z.string()) })),
  within_minutes: z.number().int().min(1).max(1440),
  min_count: z.number().int().min(2).nullable(),
  subject: z.literal('device').nullable().default(null),
})
export type EventPattern = z.infer<typeof eventPatternSchema>

export const eventPatternsResponseSchema = z.array(eventPatternSchema)
export type EventPatternsResponse = z.infer<typeof eventPatternsResponseSchema>
