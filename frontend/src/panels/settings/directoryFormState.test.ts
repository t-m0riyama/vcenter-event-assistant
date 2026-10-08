import { describe, expect, it } from 'vitest'
import type { Directory } from '../../api/schemas'
import {
  changesFromForm,
  createBody,
  emptyDirectoryForm,
  formFromDirectory,
  mappingsChanged,
  mappingsFromForm,
  parseServerUris,
  withKind,
} from './directoryFormState'

const DIRECTORY: Directory = {
  id: 'd1',
  name: 'Corp LDAP',
  kind: 'ldap',
  is_enabled: true,
  sort_order: 0,
  server_uris: ['ldaps://ldap1.example.com', 'ldaps://ldap2.example.com:1636'],
  transport_security: 'ldaps',
  tls_verify: true,
  ca_cert_pem: null,
  bind_dn: 'cn=svc,dc=example,dc=com',
  has_bind_password: true,
  timeout_seconds: 10,
  user_search_base: 'ou=people,dc=example,dc=com',
  user_search_filter: null,
  username_attribute: 'uid',
  unique_id_attribute: null,
  ad_upn_suffix: null,
  display_name_attribute: 'cn',
  email_attribute: null,
  group_mode: 'member_of',
  group_search_base: null,
  group_search_filter: null,
  group_member_attribute: null,
  group_member_value: null,
  mappings: [{ group_dn: 'cn=admins,dc=example,dc=com', role: 'admin' }],
  user_count: 2,
  created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-01T00:00:00Z',
}

describe('parseServerUris', () => {
  it('1 行に 1 つ。前後の空白と空行は除く', () => {
    expect(parseServerUris(' ldaps://a.example.com \n\n ldaps://b.example.com\n')).toEqual([
      'ldaps://a.example.com',
      'ldaps://b.example.com',
    ])
  })
})

describe('withKind', () => {
  it('種類に合わせてグループの調べ方を変える（AD は入れ子、LDAP は memberOf）', () => {
    const ad = withKind(emptyDirectoryForm(), 'ad')
    expect(ad.group_mode).toBe('ad_nested')
    expect(withKind(ad, 'ldap').group_mode).toBe('member_of')
  })

  it('種類で使えない値を消す（AD の ID 属性・検索フィルタ・ユーザー名の属性、LDAP の UPN サフィックス）', () => {
    const ldap = { ...emptyDirectoryForm(), unique_id_attribute: 'nsUniqueId', user_search_filter: '(uid={username})', username_attribute: 'uid' }
    expect(withKind(ldap, 'ad')).toMatchObject({ unique_id_attribute: '', user_search_filter: '', username_attribute: '' })
    const ad = { ...withKind(emptyDirectoryForm(), 'ad'), ad_upn_suffix: 'example.com' }
    expect(withKind(ad, 'ldap').ad_upn_suffix).toBe('')
  })
})

describe('createBody', () => {
  it('空の任意項目は null、空のパスワードは送らない、DN の空の行は除く', () => {
    const form = {
      ...emptyDirectoryForm(),
      name: ' Corp ',
      server_uris: 'ldaps://ldap.example.com',
      user_search_base: 'dc=example,dc=com',
      mappings: [
        { group_dn: ' cn=admins,dc=example,dc=com ', role: 'admin' as const },
        { group_dn: '  ', role: 'viewer' as const },
      ],
    }
    const body = createBody(form)
    expect(body).toMatchObject({
      name: 'Corp',
      kind: 'ldap',
      server_uris: ['ldaps://ldap.example.com'],
      bind_dn: null,
      bind_password: null,
      timeout_seconds: 10,
      group_member_value: null,
      mappings: [{ group_dn: 'cn=admins,dc=example,dc=com', role: 'admin' }],
    })
  })
})

describe('changesFromForm', () => {
  it('変えていなければ空', () => {
    expect(changesFromForm(DIRECTORY, formFromDirectory(DIRECTORY))).toEqual({})
  })

  it('変えた項目だけを送る。空にした任意項目は null', () => {
    const form = { ...formFromDirectory(DIRECTORY), name: 'Renamed', display_name_attribute: '', timeout_seconds: '20' }
    expect(changesFromForm(DIRECTORY, form)).toEqual({ name: 'Renamed', display_name_attribute: null, timeout_seconds: 20 })
  })

  it('サーバの一覧は中身で比べる', () => {
    const form = { ...formFromDirectory(DIRECTORY), server_uris: 'ldaps://ldap1.example.com\nldaps://ldap2.example.com:1636\n' }
    expect(changesFromForm(DIRECTORY, form)).toEqual({})
    const reordered = { ...form, server_uris: 'ldaps://ldap2.example.com:1636\nldaps://ldap1.example.com' }
    expect(changesFromForm(DIRECTORY, reordered)).toEqual({
      server_uris: ['ldaps://ldap2.example.com:1636', 'ldaps://ldap1.example.com'],
    })
  })

  it('パスワードは入力したときだけ送る。消すときは clear_bind_password', () => {
    const form = { ...formFromDirectory(DIRECTORY), bind_password: 'new-secret' }
    expect(changesFromForm(DIRECTORY, form)).toEqual({ bind_password: 'new-secret' })
    const cleared = { ...formFromDirectory(DIRECTORY), clear_bind_password: true }
    expect(changesFromForm(DIRECTORY, cleared)).toEqual({ clear_bind_password: true })
  })

  it('種類は変えられないので送らない', () => {
    const form = { ...formFromDirectory(DIRECTORY), kind: 'ad' as const }
    expect(changesFromForm(DIRECTORY, form)).toEqual({})
  })
})

describe('mappingsChanged', () => {
  it('前後の空白と空の行は無視して比べる', () => {
    const form = formFromDirectory(DIRECTORY)
    expect(mappingsChanged(DIRECTORY, form)).toBe(false)
    const padded = {
      ...form,
      mappings: [{ group_dn: ' cn=admins,dc=example,dc=com ', role: 'admin' as const }, { group_dn: '', role: 'viewer' as const }],
    }
    expect(mappingsChanged(DIRECTORY, padded)).toBe(false)
    const changed = { ...form, mappings: [{ group_dn: 'cn=admins,dc=example,dc=com', role: 'operator' as const }] }
    expect(mappingsChanged(DIRECTORY, changed)).toBe(true)
    expect(mappingsFromForm(changed)).toEqual([{ group_dn: 'cn=admins,dc=example,dc=com', role: 'operator' }])
  })
})
