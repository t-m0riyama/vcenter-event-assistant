import { z } from 'zod'

/** 保存済みダイジェスト 1 件（API の `DigestRead` に対応） */
export const digestReadSchema = z.object({
  id: z.number(),
  period_start: z.string(),
  period_end: z.string(),
  kind: z.string(),
  body_markdown: z.string(),
  status: z.string(),
  error_message: z.string().nullable(),
  llm_model: z.string().nullable(),
  created_at: z.string(),
})

export type DigestRead = z.infer<typeof digestReadSchema>

export const digestListResponseSchema = z.object({
  items: z.array(digestReadSchema),
  total: z.number(),
})

export type DigestListResponse = z.infer<typeof digestListResponseSchema>

export function parseDigestListResponse(raw: unknown): DigestListResponse {
  return digestListResponseSchema.parse(raw)
}
