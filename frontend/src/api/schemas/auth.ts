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
  /** サーバがセッションの最終利用時刻を更新する間隔（秒）。認証が無効なら null。旧サーバ互換で optional */
  session_activity_interval_seconds: z.number().int().positive().nullable().optional(),
  /** 利用者とセッションを表す値。API 応答の X-VEA-Principal と照合する。認証が無効なら null。旧サーバ互換で optional */
  principal_id: z.string().nullable().optional(),
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
