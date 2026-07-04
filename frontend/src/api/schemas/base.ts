import { z } from 'zod'

export const metricThresholdPercentSchema = z.number().min(0).max(100)
export const metricThresholdNullablePercentSchema = metricThresholdPercentSchema.nullable().optional()
export const isoOffsetDateTimeSchema = z.string().datetime({ offset: true })
export const isoUtcDateTimeSchema = isoOffsetDateTimeSchema.refine(
  (value) => value.endsWith('Z'),
  'UTC日時は末尾 Z の ISO 8601 形式で指定してください',
)
