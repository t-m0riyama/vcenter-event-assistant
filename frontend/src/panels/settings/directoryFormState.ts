import type {
  Directory,
  DirectoryKind,
  GroupMemberValue,
  GroupMode,
  GroupRoleMapping,
  TransportSecurity,
} from '../../api/schemas'

/**
 * 認証ディレクトリの編集フォームの値と、API に送る本文の変換。
 *
 * フォームは入力欄の文字列をそのまま持ち、送るときに整える（前後の空白を除き、空の任意項目は null）。
 */

/** 任意の文字列項目（空なら null として送る）。 */
const OPTIONAL_TEXT_FIELDS = [
  'ca_cert_pem',
  'bind_dn',
  'user_search_filter',
  'username_attribute',
  'unique_id_attribute',
  'ad_upn_suffix',
  'display_name_attribute',
  'email_attribute',
  'group_search_base',
  'group_search_filter',
  'group_member_attribute',
] as const

type OptionalTextField = (typeof OPTIONAL_TEXT_FIELDS)[number]

export type DirectoryFormState = {
  name: string
  kind: DirectoryKind
  is_enabled: boolean
  sort_order: string
  /** 1 行に 1 つ。 */
  server_uris: string
  transport_security: TransportSecurity
  tls_verify: boolean
  /** 新しいパスワード。空なら変えない。 */
  bind_password: string
  clear_bind_password: boolean
  timeout_seconds: string
  user_search_base: string
  group_mode: GroupMode
  group_member_value: GroupMemberValue | ''
  mappings: GroupRoleMapping[]
} & Record<OptionalTextField, string>

const DEFAULT_SORT_ORDER = 0
const DEFAULT_TIMEOUT_SECONDS = 10

export function emptyDirectoryForm(): DirectoryFormState {
  return {
    name: '',
    kind: 'ldap',
    is_enabled: true,
    sort_order: String(DEFAULT_SORT_ORDER),
    server_uris: '',
    transport_security: 'ldaps',
    tls_verify: true,
    ca_cert_pem: '',
    bind_dn: '',
    bind_password: '',
    clear_bind_password: false,
    timeout_seconds: String(DEFAULT_TIMEOUT_SECONDS),
    user_search_base: '',
    user_search_filter: '',
    username_attribute: '',
    unique_id_attribute: '',
    ad_upn_suffix: '',
    display_name_attribute: '',
    email_attribute: '',
    group_mode: 'member_of',
    group_search_base: '',
    group_search_filter: '',
    group_member_attribute: '',
    group_member_value: '',
    mappings: [],
  }
}

/** 種類を変える（新規作成のときだけ）。その種類で使えない値は既定に戻す。 */
export function withKind(form: DirectoryFormState, kind: DirectoryKind): DirectoryFormState {
  if (kind === 'ad') {
    // AD は objectGUID を ID に使い、sAMAccountName / UPN で探す。グループは入れ子も含めて調べる
    // （group_search は使えない）
    return {
      ...form,
      kind,
      unique_id_attribute: '',
      user_search_filter: '',
      username_attribute: '',
      group_mode: 'ad_nested',
    }
  }
  return { ...form, kind, ad_upn_suffix: '', group_mode: 'member_of' }
}

export function formFromDirectory(d: Directory): DirectoryFormState {
  const optional = Object.fromEntries(OPTIONAL_TEXT_FIELDS.map((f) => [f, d[f] ?? ''])) as Record<
    OptionalTextField,
    string
  >
  return {
    ...optional,
    name: d.name,
    kind: d.kind,
    is_enabled: d.is_enabled,
    sort_order: String(d.sort_order),
    server_uris: d.server_uris.join('\n'),
    transport_security: d.transport_security,
    tls_verify: d.tls_verify,
    bind_password: '',
    clear_bind_password: false,
    timeout_seconds: String(d.timeout_seconds),
    user_search_base: d.user_search_base,
    group_mode: d.group_mode,
    group_member_value: d.group_member_value ?? '',
    mappings: d.mappings.map((m) => ({ ...m })),
  }
}

export function parseServerUris(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line !== '')
}

function optionalText(value: string): string | null {
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

function integer(value: string, fallback: number): number {
  const n = Number(value.trim())
  return value.trim() === '' || !Number.isFinite(n) ? fallback : Math.trunc(n)
}

/** 対応表の行を整える（DN の前後の空白を除き、DN が空の行は除く）。 */
export function mappingsFromForm(form: DirectoryFormState): GroupRoleMapping[] {
  return form.mappings
    .map((m) => ({ group_dn: m.group_dn.trim(), role: m.role }))
    .filter((m) => m.group_dn !== '')
}

/** 種類とパスワード・対応表を除いた、保存する設定の値。 */
function settingsFromForm(form: DirectoryFormState) {
  const optional = Object.fromEntries(OPTIONAL_TEXT_FIELDS.map((f) => [f, optionalText(form[f])])) as Record<
    OptionalTextField,
    string | null
  >
  return {
    ...optional,
    name: form.name.trim(),
    is_enabled: form.is_enabled,
    sort_order: integer(form.sort_order, DEFAULT_SORT_ORDER),
    server_uris: parseServerUris(form.server_uris),
    transport_security: form.transport_security,
    tls_verify: form.tls_verify,
    timeout_seconds: integer(form.timeout_seconds, DEFAULT_TIMEOUT_SECONDS),
    user_search_base: form.user_search_base.trim(),
    group_mode: form.group_mode,
    group_member_value: form.group_member_value === '' ? null : form.group_member_value,
  }
}

/** 新規作成（``POST /api/auth/directories``）の本文。 */
export function createBody(form: DirectoryFormState) {
  return {
    ...settingsFromForm(form),
    kind: form.kind,
    bind_password: form.bind_password === '' ? null : form.bind_password,
    mappings: mappingsFromForm(form),
  }
}

function sameValue(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

/**
 * 保存済みの設定から変えた項目だけ（``PATCH`` の本文と、接続試験の ``changes``）。
 *
 * 編集を始めた時点の値と比べる。ほかの管理者が同時に変えた項目を、編集開始時の値で上書きしないため。
 * 種類は作成後に変えられないので含めない。
 */
export function changesFromForm(original: Directory, form: DirectoryFormState): Record<string, unknown> {
  const before = settingsFromForm(formFromDirectory(original))
  const after = settingsFromForm(form)
  const changes: Record<string, unknown> = {}
  for (const key of Object.keys(after) as (keyof typeof after)[]) {
    if (!sameValue(before[key], after[key])) changes[key] = after[key]
  }
  if (form.bind_password !== '') {
    changes.bind_password = form.bind_password
  } else if (form.clear_bind_password) {
    changes.clear_bind_password = true
  }
  return changes
}

/** 対応表を変えたか（前後の空白と DN が空の行は無視する）。 */
export function mappingsChanged(original: Directory, form: DirectoryFormState): boolean {
  return !sameValue(mappingsFromForm(formFromDirectory(original)), mappingsFromForm(form))
}

export const INSECURE_TLS_WARNING = '証明書を検証しません（中間者攻撃に弱い状態です）'
export const PLAINTEXT_WARNING = '暗号化しない接続です（パスワードが平文で流れます）'

/** フォームの値から、一覧やフォームに出す警告。 */
export function connectionWarnings(form: Pick<DirectoryFormState, 'transport_security' | 'tls_verify'>): string[] {
  if (form.transport_security === 'none') return [PLAINTEXT_WARNING]
  return form.tls_verify ? [] : [INSECURE_TLS_WARNING]
}
