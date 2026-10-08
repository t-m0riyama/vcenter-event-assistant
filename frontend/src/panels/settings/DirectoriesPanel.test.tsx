/**
 * @vitest-environment happy-dom
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { onUnauthorized } from '../../api'
import type { Directory, DirectoryPolicy, Me } from '../../api/schemas'
import { AuthContext } from '../../auth/authContext'
import { roleAtLeast } from '../../auth/roles'
import { DirectoriesPanel } from './DirectoriesPanel'

function directory(overrides: Partial<Directory>): Directory {
  return {
    id: 'd-ldap',
    name: 'Corp LDAP',
    kind: 'ldap',
    is_enabled: true,
    sort_order: 0,
    server_uris: ['ldaps://ldap.example.com'],
    transport_security: 'ldaps',
    tls_verify: true,
    ca_cert_pem: null,
    bind_dn: 'cn=svc,dc=example,dc=com',
    has_bind_password: true,
    timeout_seconds: 10,
    user_search_base: 'ou=people,dc=example,dc=com',
    user_search_filter: null,
    username_attribute: null,
    unique_id_attribute: null,
    ad_upn_suffix: null,
    display_name_attribute: null,
    email_attribute: null,
    group_mode: 'member_of',
    group_search_base: null,
    group_search_filter: null,
    group_member_attribute: null,
    group_member_value: null,
    mappings: [{ group_dn: 'cn=admins,dc=example,dc=com', role: 'admin' }],
    user_count: 0,
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    ...overrides,
  }
}

const DIRECTORIES: Directory[] = [
  directory({}),
  directory({
    id: 'd-ad',
    name: 'Corp AD',
    kind: 'ad',
    is_enabled: false,
    tls_verify: false,
    group_mode: 'ad_nested',
    user_count: 3,
    server_uris: ['ldaps://dc1.example.com'],
  }),
]

const ALLOW_ALL: DirectoryPolicy = { allow_insecure_tls: true, allow_no_transport_security: true }

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
}

type Call = { url: string; method: string; body: unknown }

function stubApi(
  handler: (call: Call) => Response | Promise<Response> | undefined = () => undefined,
  {
    list = DIRECTORIES,
    policy = ALLOW_ALL,
    me = null,
  }: { list?: Directory[]; policy?: DirectoryPolicy; me?: Me | null } = {},
) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const call = {
        url: String(input),
        method: init?.method ?? 'GET',
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      }
      calls.push(call)
      const custom = handler(call)
      if (custom) return Promise.resolve(custom)
      if (call.url === '/api/auth/directories' && call.method === 'GET') return Promise.resolve(json(list))
      if (call.url === '/api/auth/directories/policy') return Promise.resolve(json(policy))
      // 保存の後のセッションの確認。既定は失効（401）
      if (call.url === '/api/auth/me') {
        return Promise.resolve(me ? json(me) : json({ detail: 'ログインが必要です。' }, 401))
      }
      if (call.method === 'DELETE') return Promise.resolve(new Response(null, { status: 204 }))
      if (call.url.endsWith('/test')) {
        return Promise.resolve(json({ ok: true, stages: [{ stage: 'connect', ok: true, message: '接続できました' }] }))
      }
      return Promise.resolve(json(list[0], call.method === 'POST' ? 201 : 200))
    }),
  )
  return calls
}

const LOCAL_ADMIN: Me = {
  auth_enabled: true,
  username: 'admin',
  display_name: null,
  role: 'admin',
  realm: 'local',
  can_change_password: true,
}

/** Corp LDAP（d-ldap）でログインしている admin。 */
const LDAP_ADMIN: Me = { ...LOCAL_ADMIN, username: 'alice', realm: 'dir:d-ldap', can_change_password: false }

function renderPanel(onError = vi.fn(), me: Me = LOCAL_ADMIN) {
  render(
    <AuthContext.Provider
      value={{ me, hasRole: (r) => roleAtLeast(me.role, r), logout: async () => {}, refresh: async () => {} }}
    >
      <DirectoriesPanel onError={onError} />
    </AuthContext.Provider>,
  )
  return onError
}

function verificationError(code: string, detail: string) {
  return new Response(JSON.stringify({ detail }), {
    status: 409,
    headers: { 'Content-Type': 'application/json', 'X-VEA-Error-Code': code },
  })
}

function row(name: string): HTMLElement {
  const cell = screen.getByText(name, { selector: '.directories-panel__name' })
  const tr = cell.closest('tr')
  if (!tr) throw new Error(`row for ${name} not found`)
  return tr
}

function editor(): HTMLElement {
  return screen.getByRole('region', { name: 'ディレクトリの設定' })
}

async function openEdit(name: string) {
  await screen.findByText(name, { selector: '.directories-panel__name' })
  fireEvent.click(within(row(name)).getByRole('button', { name: '編集' }))
  return editor()
}

function mutations(calls: Call[]) {
  return calls.filter((c) => c.method !== 'GET')
}

describe('DirectoriesPanel', () => {
  beforeEach(() => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('一覧に種類・状態・ユーザー数と、証明書を検証しない設定の警告を出す', async () => {
    stubApi()
    renderPanel()
    await screen.findByText('Corp LDAP', { selector: '.directories-panel__name' })

    const ldap = row('Corp LDAP')
    expect(ldap).toHaveTextContent('LDAP')
    expect(ldap).toHaveTextContent('有効')
    expect(within(ldap).queryByText(/証明書を検証しません/)).not.toBeInTheDocument()
    // 有効なディレクトリは削除できない（先に無効にする）
    expect(within(ldap).getByRole('button', { name: '削除' })).toBeDisabled()

    const ad = row('Corp AD')
    expect(ad).toHaveTextContent('Active Directory')
    expect(ad).toHaveTextContent('無効')
    expect(ad).toHaveTextContent('3')
    expect(within(ad).getByText('証明書を検証しません（中間者攻撃に弱い状態です）')).toBeInTheDocument()
    expect(within(ad).getByRole('button', { name: '削除' })).toBeEnabled()
  })

  it('新規作成では入力した設定と対応表を 1 回で送る', async () => {
    const calls = stubApi()
    renderPanel()
    await screen.findByText('Corp LDAP', { selector: '.directories-panel__name' })
    fireEvent.click(screen.getByRole('button', { name: 'ディレクトリを追加' }))
    const form = editor()

    fireEvent.change(within(form).getByLabelText('名前'), { target: { value: 'New LDAP' } })
    fireEvent.change(within(form).getByLabelText(/^サーバ（1 行に 1 つ/), { target: { value: 'ldaps://new.example.com\n' } })
    fireEvent.change(within(form).getByLabelText('検索ベース'), { target: { value: 'dc=example,dc=com' } })
    fireEvent.change(within(form).getByLabelText(/^ID 属性/), { target: { value: 'nsUniqueId' } })
    fireEvent.click(within(form).getByRole('button', { name: '対応を追加' }))
    fireEvent.change(within(form).getByLabelText('1 行目のグループの DN'), {
      target: { value: 'cn=admins,dc=example,dc=com' },
    })
    fireEvent.change(within(form).getByLabelText('1 行目のロール'), { target: { value: 'admin' } })
    fireEvent.click(within(form).getByRole('button', { name: '追加' }))

    expect(await screen.findByRole('status')).toHaveTextContent('New LDAP を追加しました。')
    expect(mutations(calls)).toEqual([
      expect.objectContaining({
        url: '/api/auth/directories',
        method: 'POST',
        body: expect.objectContaining({
          name: 'New LDAP',
          kind: 'ldap',
          server_uris: ['ldaps://new.example.com'],
          user_search_base: 'dc=example,dc=com',
          unique_id_attribute: 'nsUniqueId',
          bind_password: null,
          mappings: [{ group_dn: 'cn=admins,dc=example,dc=com', role: 'admin' }],
        }),
      }),
    ])
    expect(screen.queryByRole('region', { name: 'ディレクトリの設定' })).not.toBeInTheDocument()
  })

  it('AD を選ぶと、ID 属性の代わりに UPN サフィックスを出し、グループは入れ子を含めて調べる', async () => {
    stubApi()
    renderPanel()
    await screen.findByText('Corp LDAP', { selector: '.directories-panel__name' })
    fireEvent.click(screen.getByRole('button', { name: 'ディレクトリを追加' }))
    const form = editor()
    fireEvent.change(within(form).getByLabelText('種類'), { target: { value: 'ad' } })

    expect(within(form).queryByLabelText(/^ID 属性/)).not.toBeInTheDocument()
    expect(within(form).queryByLabelText(/^検索フィルタ/)).not.toBeInTheDocument()
    expect(within(form).getByLabelText(/^UPN サフィックス/)).toBeInTheDocument()
    expect(within(form).getByLabelText('グループの調べ方')).toHaveValue('ad_nested')
  })

  it('編集では変えた設定と対応表だけを 1 回の PATCH で送る', async () => {
    const calls = stubApi()
    renderPanel()
    const form = await openEdit('Corp LDAP')
    // 種類は作成後に変えられない
    expect(within(form).getByLabelText('種類')).toBeDisabled()

    fireEvent.change(within(form).getByLabelText('名前'), { target: { value: 'Renamed' } })
    fireEvent.change(within(form).getByLabelText('1 行目のロール'), { target: { value: 'operator' } })
    fireEvent.click(within(form).getByRole('button', { name: '保存' }))

    expect(await screen.findByRole('status')).toHaveTextContent('Renamed を保存しました。')
    expect(mutations(calls)).toEqual([
      {
        url: '/api/auth/directories/d-ldap',
        method: 'PATCH',
        body: { name: 'Renamed', mappings: [{ group_dn: 'cn=admins,dc=example,dc=com', role: 'operator' }] },
      },
    ])
  })

  it('何も変えずに保存したら送らずに閉じる', async () => {
    const calls = stubApi()
    renderPanel()
    const form = await openEdit('Corp LDAP')
    fireEvent.click(within(form).getByRole('button', { name: '保存' }))
    await waitFor(() => expect(screen.queryByRole('region', { name: 'ディレクトリの設定' })).not.toBeInTheDocument())
    expect(mutations(calls)).toEqual([])
  })

  it('サービスアカウントのパスワードは入力したときだけ送り、消すときは clear_bind_password', async () => {
    const calls = stubApi()
    renderPanel()
    let form = await openEdit('Corp LDAP')
    const password = within(form).getByLabelText('サービスアカウントのパスワード')
    expect(password).toHaveAttribute('placeholder', '設定済み（変えるときだけ入力）')
    fireEvent.click(within(form).getByLabelText('保存済みのパスワードを消す'))
    expect(password).toBeDisabled()
    fireEvent.click(within(form).getByRole('button', { name: '保存' }))
    await screen.findByRole('status')
    expect(mutations(calls).at(-1)?.body).toEqual({ clear_bind_password: true })

    form = await openEdit('Corp LDAP')
    fireEvent.change(within(form).getByLabelText('サービスアカウントのパスワード'), { target: { value: 'new-secret' } })
    fireEvent.click(within(form).getByRole('button', { name: '保存' }))
    await waitFor(() => expect(mutations(calls)).toHaveLength(2))
    expect(mutations(calls).at(-1)?.body).toEqual({ bind_password: 'new-secret' })
  })

  it('ユーザーがいる LDAP では ID 属性を変えられず、作り直しの手順を出す', async () => {
    stubApi(undefined, { list: [directory({ user_count: 2, unique_id_attribute: 'nsUniqueId' })] })
    renderPanel()
    const form = await openEdit('Corp LDAP')
    const id = within(form).getByLabelText(/^ID 属性/)
    expect(id).toHaveAttribute('readonly')
    expect(id).toHaveAccessibleDescription(/ID 属性は変更できません。.*削除し、作り直してください/)
  })

  it('証明書の検証をやめるときは確認し、断ればそのまま', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    stubApi()
    renderPanel()
    const form = await openEdit('Corp LDAP')
    const verify = within(form).getByLabelText('サーバ証明書を検証する')
    fireEvent.click(verify)
    expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining('中間者攻撃'))
    expect(verify).toBeChecked()

    confirmSpy.mockReturnValue(true)
    fireEvent.click(verify)
    expect(verify).not.toBeChecked()
    expect(within(form).getByText('証明書を検証しません（中間者攻撃に弱い状態です）')).toBeInTheDocument()
  })

  it('全体の方針で禁止された接続は選べず、理由を出す', async () => {
    stubApi(undefined, { policy: { allow_insecure_tls: false, allow_no_transport_security: false } })
    renderPanel()
    const form = await openEdit('Corp LDAP')
    expect(within(form).getByLabelText('サーバ証明書を検証する')).toBeDisabled()
    expect(within(form).getByText(/VEA_DIRECTORY_ALLOW_INSECURE_TLS=false/)).toBeInTheDocument()
    expect(within(form).getByRole('option', { name: '暗号化しない（ldap://）' })).toBeDisabled()
    expect(within(form).getByText('本番環境では暗号化しない接続は使えません。')).toBeInTheDocument()
  })

  it('禁止されていても、検証しない設定のディレクトリを検証する側へ戻せる', async () => {
    stubApi(undefined, {
      list: [directory({ tls_verify: false })],
      policy: { allow_insecure_tls: false, allow_no_transport_security: true },
    })
    renderPanel()
    const form = await openEdit('Corp LDAP')
    const verify = within(form).getByLabelText('サーバ証明書を検証する')
    expect(verify).toBeEnabled()
    fireEvent.click(verify)
    expect(verify).toBeChecked()
    expect(verify).toBeDisabled()
  })

  it('保存済みのディレクトリの接続試験は、編集中の変更を重ねて送り、段階ごとの結果を出す', async () => {
    const calls = stubApi((call) =>
      call.url.endsWith('/test')
        ? json({
            ok: false,
            stages: [
              { stage: 'connect', ok: true, message: '接続できました' },
              { stage: 'user_search', ok: true, message: 'ユーザーが見つかりました' },
              { stage: 'unique_id', ok: false, message: 'ID 属性 nsUniqueId の値が取れません' },
            ],
          })
        : undefined,
    )
    renderPanel()
    const form = await openEdit('Corp LDAP')
    fireEvent.change(within(form).getByLabelText(/^ID 属性/), { target: { value: 'nsUniqueId' } })
    fireEvent.change(within(form).getByLabelText('試すユーザー名'), { target: { value: ' alice ' } })
    fireEvent.click(within(form).getByRole('button', { name: '接続試験' }))

    const result = await screen.findByLabelText('接続試験の結果')
    expect(result).toHaveTextContent('接続試験に失敗しました。')
    expect(result).toHaveTextContent('ユーザーの ID')
    expect(within(result).getByRole('alert')).toHaveTextContent('このユーザーは ID 属性の値が取れないため、ログインできません。')
    expect(mutations(calls)).toEqual([
      {
        url: '/api/auth/directories/d-ldap/test',
        method: 'POST',
        body: { username: 'alice', password: null, changes: { unique_id_attribute: 'nsUniqueId' }, mappings: null },
      },
    ])
  })

  it('新規作成の接続試験は、まだ保存していない設定で試す', async () => {
    const calls = stubApi()
    renderPanel()
    await screen.findByText('Corp LDAP', { selector: '.directories-panel__name' })
    fireEvent.click(screen.getByRole('button', { name: 'ディレクトリを追加' }))
    const form = editor()
    fireEvent.change(within(form).getByLabelText('名前'), { target: { value: 'New' } })
    fireEvent.change(within(form).getByLabelText(/^サーバ（1 行に 1 つ/), { target: { value: 'ldaps://new.example.com' } })
    fireEvent.change(within(form).getByLabelText('試すユーザー名'), { target: { value: 'alice' } })
    fireEvent.change(within(form).getByLabelText('試すユーザーのパスワード'), { target: { value: 'pw' } })
    fireEvent.click(within(form).getByRole('button', { name: '接続試験' }))

    expect(await screen.findByLabelText('接続試験の結果')).toHaveTextContent('接続試験に成功しました。')
    expect(mutations(calls)).toEqual([
      expect.objectContaining({
        url: '/api/auth/directories/test',
        method: 'POST',
        body: expect.objectContaining({ name: 'New', server_uris: ['ldaps://new.example.com'], username: 'alice', password: 'pw' }),
      }),
    ])
  })

  it('無効なディレクトリは確認してから削除する', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const calls = stubApi()
    renderPanel()
    await screen.findByText('Corp AD', { selector: '.directories-panel__name' })
    fireEvent.click(within(row('Corp AD')).getByRole('button', { name: '削除' }))

    expect(await screen.findByRole('status')).toHaveTextContent('Corp AD を削除しました。')
    expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining('配下のユーザー 3 人'))
    expect(mutations(calls)).toEqual([{ url: '/api/auth/directories/d-ad', method: 'DELETE', body: undefined }])
  })

  it('保存の失敗（422 や 409）はサーバの理由を出し、フォームは閉じない', async () => {
    stubApi((call) =>
      call.method === 'PATCH' ? json({ detail: 'グループの DN の形式が正しくありません: bad' }, 422) : undefined,
    )
    const onError = renderPanel()
    const form = await openEdit('Corp LDAP')
    fireEvent.change(within(form).getByLabelText('1 行目のグループの DN'), { target: { value: 'bad' } })
    fireEvent.click(within(form).getByRole('button', { name: '保存' }))

    await waitFor(() => expect(onError).toHaveBeenCalledWith('グループの DN の形式が正しくありません: bad'))
    expect(screen.getByRole('region', { name: 'ディレクトリの設定' })).toBeInTheDocument()
  })

  describe('保存の前の確認（Issue #254）', () => {
    it('名前だけの変更は確かめずに保存する', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm')
      const calls = stubApi()
      renderPanel()
      const form = await openEdit('Corp LDAP')
      fireEvent.change(within(form).getByLabelText('名前'), { target: { value: 'Renamed' } })
      fireEvent.click(within(form).getByRole('button', { name: '保存' }))
      await screen.findByRole('status')
      expect(confirmSpy).not.toHaveBeenCalled()
      expect(mutations(calls)).toHaveLength(1)
    })

    it('認証に関わる変更は、試験を促し、ログイン中の利用者がログアウトされることを確かめる', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
      stubApi()
      renderPanel()
      const form = await openEdit('Corp LDAP')
      fireEvent.change(within(form).getByLabelText('検索ベース'), { target: { value: 'ou=staff,dc=example,dc=com' } })
      fireEvent.click(within(form).getByRole('button', { name: '保存' }))
      await screen.findByRole('status')
      expect(confirmSpy.mock.calls.map(([m]) => m)).toEqual([
        expect.stringContaining('接続試験が成功していません'),
        expect.stringContaining('ローカルや別のディレクトリの利用者は影響を受けません'),
      ])
    })

    it('ログアウトの確認を断れば送らない', async () => {
      vi.spyOn(window, 'confirm').mockImplementation((m) => !String(m).includes('ログアウト'))
      const calls = stubApi()
      renderPanel()
      const form = await openEdit('Corp LDAP')
      fireEvent.change(within(form).getByLabelText('1 行目のロール'), { target: { value: 'operator' } })
      fireEvent.click(within(form).getByRole('button', { name: '保存' }))
      await waitFor(() => expect(window.confirm).toHaveBeenCalledTimes(2))
      expect(mutations(calls)).toEqual([])
    })

    it('編集中の値で試験が成功していれば、試験は促さない（値を変えたら再び促す）', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
      stubApi()
      renderPanel()
      const form = await openEdit('Corp LDAP')
      fireEvent.change(within(form).getByLabelText('タイムアウト（秒）'), { target: { value: '20' } })
      fireEvent.click(within(form).getByRole('button', { name: '接続試験' }))
      await screen.findByLabelText('接続試験の結果')
      fireEvent.click(within(form).getByRole('button', { name: '保存' }))
      await screen.findByText('Corp LDAP を保存しました。')
      // タイムアウトはログアウトさせないので、ログアウトの確認も出ない
      expect(confirmSpy).not.toHaveBeenCalled()
    })

    it('資格情報を求められたら入力してもらい、同じ変更に verification を付けて送り直す', async () => {
      let attempts = 0
      const calls = stubApi((call) => {
        if (call.method !== 'PATCH') return undefined
        attempts += 1
        if (attempts === 1) return verificationError('directory_verification_required', '確かめてください')
        if (attempts === 2) return verificationError('directory_verification_failed', '管理者として確かめられませんでした')
        return undefined
      })
      renderPanel()
      const form = await openEdit('Corp LDAP')
      fireEvent.change(within(form).getByLabelText('1 行目のロール'), { target: { value: 'operator' } })
      fireEvent.click(within(form).getByRole('button', { name: '保存' }))

      const dialog = await screen.findByRole('dialog', { name: '管理者としてログインできるか確かめる' })
      expect(within(dialog).queryByRole('alert')).not.toBeInTheDocument()
      fireEvent.change(within(dialog).getByLabelText('確認に使うユーザー名'), { target: { value: ' alice ' } })
      fireEvent.change(within(dialog).getByLabelText('確認に使うパスワード'), { target: { value: 'wrong' } })
      fireEvent.click(within(dialog).getByRole('button', { name: '確かめて保存' }))

      // 確かめられなければ理由を出し、パスワードを入れ直してもらう
      expect(await within(dialog).findByRole('alert')).toHaveTextContent('管理者として確かめられませんでした')
      expect(within(dialog).getByLabelText('確認に使うパスワード')).toHaveValue('')
      fireEvent.change(within(dialog).getByLabelText('確認に使うパスワード'), { target: { value: 'secret' } })
      fireEvent.click(within(dialog).getByRole('button', { name: '確かめて保存' }))

      expect(await screen.findByText('Corp LDAP を保存しました。')).toBeInTheDocument()
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      const patches = mutations(calls).filter((c) => c.method === 'PATCH')
      const changes = { mappings: [{ group_dn: 'cn=admins,dc=example,dc=com', role: 'operator' }] }
      expect(patches.map((c) => c.body)).toEqual([
        changes,
        { ...changes, verification: { username: 'alice', password: 'wrong' } },
        { ...changes, verification: { username: 'alice', password: 'secret' } },
      ])
    })

    it('資格情報の入力をやめたら保存しない', async () => {
      const calls = stubApi((call) =>
        call.method === 'PATCH' ? verificationError('directory_verification_required', '確かめてください') : undefined,
      )
      renderPanel()
      const form = await openEdit('Corp LDAP')
      fireEvent.change(within(form).getByLabelText('1 行目のロール'), { target: { value: 'operator' } })
      fireEvent.click(within(form).getByRole('button', { name: '保存' }))
      const dialog = await screen.findByRole('dialog', { name: '管理者としてログインできるか確かめる' })
      fireEvent.click(within(dialog).getByRole('button', { name: 'キャンセル' }))
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
      expect(mutations(calls)).toHaveLength(1)
      // 編集中の値は残る
      expect(within(editor()).getByLabelText('1 行目のロール')).toHaveValue('operator')
    })

    it('ほかの 409（管理者がいなくなる変更など）は理由を出すだけで、資格情報は求めない', async () => {
      stubApi((call) =>
        call.method === 'PATCH'
          ? json({ detail: 'ログインできる管理者がいなくなるため、この対応表は保存できません。' }, 409)
          : undefined,
      )
      const onError = renderPanel()
      const form = await openEdit('Corp LDAP')
      fireEvent.change(within(form).getByLabelText('1 行目のロール'), { target: { value: 'operator' } })
      fireEvent.click(within(form).getByRole('button', { name: '保存' }))
      await waitFor(() =>
        expect(onError).toHaveBeenCalledWith('ログインできる管理者がいなくなるため、この対応表は保存できません。'),
      )
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })

    it('自分がログインしているディレクトリは無効にできず、理由を出す', async () => {
      stubApi()
      renderPanel(vi.fn(), LDAP_ADMIN)
      const form = await openEdit('Corp LDAP')
      const enabled = within(form).getByLabelText(/^有効/)
      expect(enabled).toBeDisabled()
      expect(enabled).toHaveAccessibleDescription(/このディレクトリでログインしているため、無効にできません/)

      // 別のディレクトリは無効にできる
      fireEvent.click(within(form).getByRole('button', { name: 'キャンセル' }))
      const other = await openEdit('Corp AD')
      expect(within(other).getByLabelText(/^有効/)).toBeEnabled()
    })

    it('自分のディレクトリの認証に関わる変更を保存したら、理由を添えてログイン画面に戻す', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
      const listener = vi.fn()
      const off = onUnauthorized(listener)
      try {
        stubApi()
        renderPanel(vi.fn(), LDAP_ADMIN)
        const form = await openEdit('Corp LDAP')
        fireEvent.change(within(form).getByLabelText('1 行目のロール'), { target: { value: 'operator' } })
        fireEvent.click(within(form).getByRole('button', { name: '保存' }))
        await waitFor(() => expect(listener).toHaveBeenCalledWith(expect.stringContaining('ログアウトしました')))
        expect(confirmSpy).toHaveBeenLastCalledWith(expect.stringContaining('あなたもこのディレクトリでログインしている'))
      } finally {
        off()
      }
    })

    it('自分のディレクトリでも、ログアウトさせない変更ならログイン画面に戻さない', async () => {
      const listener = vi.fn()
      const off = onUnauthorized(listener)
      try {
        stubApi()
        renderPanel(vi.fn(), LDAP_ADMIN)
        const form = await openEdit('Corp LDAP')
        fireEvent.change(within(form).getByLabelText('名前'), { target: { value: 'Renamed' } })
        fireEvent.click(within(form).getByRole('button', { name: '保存' }))
        await screen.findByText('Renamed を保存しました。')
        expect(listener).not.toHaveBeenCalled()
      } finally {
        off()
      }
    })

    it('サーバがセッションを失効させなかったら（DN の表記の違いだけなど）、ログイン画面に戻さず一覧を読み直す', async () => {
      const listener = vi.fn()
      const off = onUnauthorized(listener)
      try {
        const calls = stubApi(undefined, { me: LDAP_ADMIN })
        renderPanel(vi.fn(), LDAP_ADMIN)
        const form = await openEdit('Corp LDAP')
        // サーバは DN を正規化して比べるので、大文字にしただけでは失効させない
        fireEvent.change(within(form).getByLabelText('1 行目のグループの DN'), {
          target: { value: 'CN=Admins,DC=example,DC=com' },
        })
        fireEvent.click(within(form).getByRole('button', { name: '保存' }))
        expect(await screen.findByText('Corp LDAP を保存しました。')).toBeInTheDocument()
        expect(listener).not.toHaveBeenCalled()
        const afterSave = calls.slice(calls.findIndex((c) => c.method === 'PATCH'))
        expect(afterSave.map((c) => c.url)).toContain('/api/auth/directories')
      } finally {
        off()
      }
    })

    it('対応表の並べ替えだけなら変更として扱わない', async () => {
      const calls = stubApi(undefined, {
        list: [
          directory({
            mappings: [
              { group_dn: 'cn=admins,dc=example,dc=com', role: 'admin' },
              { group_dn: 'cn=ops,dc=example,dc=com', role: 'operator' },
            ],
          }),
        ],
      })
      renderPanel()
      const form = await openEdit('Corp LDAP')
      // 1 行目を外して末尾に足し直す
      fireEvent.click(within(form).getByRole('button', { name: '1 行目の対応を外す' }))
      fireEvent.click(within(form).getByRole('button', { name: '対応を追加' }))
      fireEvent.change(within(form).getByLabelText('2 行目のグループの DN'), {
        target: { value: 'cn=admins,dc=example,dc=com' },
      })
      fireEvent.change(within(form).getByLabelText('2 行目のロール'), { target: { value: 'admin' } })
      fireEvent.click(within(form).getByRole('button', { name: '保存' }))
      await waitFor(() => expect(screen.queryByRole('region', { name: 'ディレクトリの設定' })).not.toBeInTheDocument())
      expect(mutations(calls)).toEqual([])
    })

    it('確かめている間はダイアログを閉じられない（閉じても保存が続くため）', async () => {
      let release: (r: Response) => void = () => {}
      let attempts = 0
      stubApi((call) => {
        if (call.method !== 'PATCH') return undefined
        attempts += 1
        if (attempts === 1) return verificationError('directory_verification_required', '確かめてください')
        return new Promise<Response>((resolve) => {
          release = resolve
        })
      })
      renderPanel()
      const form = await openEdit('Corp LDAP')
      fireEvent.change(within(form).getByLabelText('1 行目のロール'), { target: { value: 'operator' } })
      fireEvent.click(within(form).getByRole('button', { name: '保存' }))
      const dialog = await screen.findByRole('dialog', { name: '管理者としてログインできるか確かめる' })
      fireEvent.change(within(dialog).getByLabelText('確認に使うユーザー名'), { target: { value: 'alice' } })
      fireEvent.change(within(dialog).getByLabelText('確認に使うパスワード'), { target: { value: 'secret' } })
      fireEvent.click(within(dialog).getByRole('button', { name: '確かめて保存' }))

      await waitFor(() => expect(within(dialog).getByRole('button', { name: 'キャンセル' })).toBeDisabled())
      expect(within(dialog).getByRole('button', { name: '閉じる' })).toBeDisabled()
      // Esc（cancel イベント）でも閉じない
      const cancel = new Event('cancel', { cancelable: true })
      dialog.dispatchEvent(cancel)
      expect(cancel.defaultPrevented).toBe(true)

      release(json(directory({})))
      expect(await screen.findByText('Corp LDAP を保存しました。')).toBeInTheDocument()
    })
  })
})
