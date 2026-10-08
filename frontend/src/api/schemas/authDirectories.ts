import { z } from 'zod'
import { roleSchema } from './auth'

/** 認証ディレクトリの種類。 */
export const directoryKindSchema = z.enum(['ad', 'ldap'])
export type DirectoryKind = z.infer<typeof directoryKindSchema>

/** 接続の暗号化。 */
export const transportSecuritySchema = z.enum(['ldaps', 'starttls', 'none'])
export type TransportSecurity = z.infer<typeof transportSecuritySchema>

/** グループ所属の調べ方。 */
export const groupModeSchema = z.enum(['ad_nested', 'member_of', 'group_search'])
export type GroupMode = z.infer<typeof groupModeSchema>

export const groupMemberValueSchema = z.enum(['dn', 'username'])
export type GroupMemberValue = z.infer<typeof groupMemberValueSchema>

export const groupRoleMappingSchema = z.object({
  group_dn: z.string(),
  role: roleSchema,
})
export type GroupRoleMapping = z.infer<typeof groupRoleMappingSchema>

/** ``/api/auth/directories`` の 1 件（admin のみ）。bind パスワードは返らない（``has_bind_password`` だけ）。 */
export const directorySchema = z.object({
  id: z.string(),
  name: z.string(),
  kind: directoryKindSchema,
  is_enabled: z.boolean(),
  sort_order: z.number().int(),
  server_uris: z.array(z.string()),
  transport_security: transportSecuritySchema,
  tls_verify: z.boolean(),
  ca_cert_pem: z.string().nullable().optional(),
  bind_dn: z.string().nullable().optional(),
  has_bind_password: z.boolean(),
  timeout_seconds: z.number().int(),
  user_search_base: z.string(),
  user_search_filter: z.string().nullable().optional(),
  username_attribute: z.string().nullable().optional(),
  unique_id_attribute: z.string().nullable().optional(),
  ad_upn_suffix: z.string().nullable().optional(),
  display_name_attribute: z.string().nullable().optional(),
  email_attribute: z.string().nullable().optional(),
  group_mode: groupModeSchema,
  group_search_base: z.string().nullable().optional(),
  group_search_filter: z.string().nullable().optional(),
  group_member_attribute: z.string().nullable().optional(),
  group_member_value: groupMemberValueSchema.nullable().optional(),
  mappings: z.array(groupRoleMappingSchema),
  user_count: z.number().int(),
  created_at: z.string(),
  updated_at: z.string(),
})
export type Directory = z.infer<typeof directorySchema>
export const directoryListSchema = z.array(directorySchema)

/** ``GET /api/auth/directories/policy``。今の設定で許される接続の方針。 */
export const directoryPolicySchema = z.object({
  /** 証明書を検証しない設定を保存できるか（``VEA_DIRECTORY_ALLOW_INSECURE_TLS``）。 */
  allow_insecure_tls: z.boolean(),
  /** 暗号化しない接続（``none``）を保存できるか（本番では不可）。 */
  allow_no_transport_security: z.boolean(),
})
export type DirectoryPolicy = z.infer<typeof directoryPolicySchema>

export const directoryTestStageNameSchema = z.enum(['connect', 'user_search', 'unique_id', 'user_bind', 'groups'])
export type DirectoryTestStageName = z.infer<typeof directoryTestStageNameSchema>

/** 接続試験の結果。段階ごとの成否。 */
export const directoryTestResponseSchema = z.object({
  ok: z.boolean(),
  stages: z.array(
    z.object({
      stage: directoryTestStageNameSchema,
      ok: z.boolean(),
      message: z.string(),
    }),
  ),
})
export type DirectoryTestResponse = z.infer<typeof directoryTestResponseSchema>
