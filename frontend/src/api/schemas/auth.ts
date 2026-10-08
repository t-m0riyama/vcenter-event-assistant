import { z } from 'zod'

/** ロール（admin ⊃ operator ⊃ viewer）。 */
export const roleSchema = z.enum(['viewer', 'operator', 'admin'])

export type Role = z.infer<typeof roleSchema>

/** ``GET /api/auth/me`` とログイン応答。 */
export const meSchema = z.object({
  auth_enabled: z.boolean(),
  username: z.string(),
  display_name: z.string().nullable().optional(),
  role: roleSchema,
  realm: z.string(),
  can_change_password: z.boolean(),
})

export type Me = z.infer<typeof meSchema>

export const realmSchema = z.object({
  id: z.string(),
  name: z.string(),
  kind: z.string(),
})

export type Realm = z.infer<typeof realmSchema>

/** ``GET /api/auth/realms``。 */
export const realmsResponseSchema = z.object({
  auth_enabled: z.boolean(),
  realms: z.array(realmSchema),
})

export type RealmsResponse = z.infer<typeof realmsResponseSchema>
