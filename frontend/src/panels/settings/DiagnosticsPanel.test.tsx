import { generateKeyPairSync } from 'node:crypto'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DiagnosticsPanel } from './DiagnosticsPanel'
import { generateSshUploadKeys, opensshPrivateKeyBegin } from '../../test/sshUploadKeys'
import { SchemaFields } from './PluginSetupPanel'

const base = '/api/diagnostics'
const vc = {
  id: 'vc1', name: '運用 vCenter', host: 'vc.example.net', port: 443,
  username: 'reader', is_enabled: true, created_at: '2026-11-26T00:00:00Z',
}
const esxi = { id: 'host-42', name: '運用 ESXi', host: 'esxi.example.net' }
const key = { id: 'key1', name: '診断の鍵', public_key: 'ssh-rsa PUBLIC' }
const connection = {
  id: 'ssh1', name: '接続先', host: esxi.host, port: 22, username: 'diagnostics',
  credential_id: key.id, revision: 1, approved: false, fingerprint: null, candidate_fingerprint: null,
}
const meta = { revision: 'original', created_by: 'admin', updated_by: 'admin', created_at: vc.created_at, updated_at: vc.created_at }
const target = {
  ...meta, id: 'target1', vcenter_id: vc.id, product: 'esxi',
  host_moid: esxi.id, host_name: esxi.name, ssh_connection_id: connection.id,
}
const command = {
  ...meta, id: 'command1', product: 'esxi', title: '既存のコマンド',
  description: '', template: 'hostname', param_definitions: [],
}
const parameterTypes = ['vmnic', 'vmk', 'ipv4', 'device']
const uploadKeys = generateSshUploadKeys()
const privateKey = uploadKeys[0].privateKey
const testKeyFragment = privateKey.split('\n')[1]

function json(data: unknown, status = 200, headers?: Record<string, string>) {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json', ...headers } })
}

const fetchMock = vi.fn<(url: string, options: RequestInit) => Promise<Response>>()
let targets: (typeof target)[]
let commands: (typeof command)[]
let vcenters: (typeof vc)[]
let readCommands: () => Response
let readTargets: () => Response
let readHosts: () => Response
let readSSH: () => Response | Promise<Response>
let keys: unknown[]
let connections: unknown[]
let write: (url: string, method: string, body: unknown) => Response

beforeEach(() => {
  targets = []
  commands = []
  vcenters = [vc]
  readCommands = () => json({ custom: commands, builtin: [], parameter_types: parameterTypes })
  readTargets = () => json(targets)
  readHosts = () => json([esxi])
  readSSH = () => json(connections)
  keys = [key]
  connections = [connection]
  write = () => json({}, 405)
  fetchMock.mockReset()
  fetchMock.mockImplementation(async (url, options) => {
    if (options.method) {
      const response = write(url, options.method, options.body && JSON.parse(String(options.body)))
      if (response.ok && options.method !== 'DELETE') {
        if (url.startsWith(`${base}/targets`)) {
          const saved = await response.clone().json() as typeof target
          targets = [...targets.filter(item => item.id !== saved.id), saved].sort((a, b) => a.host_name.localeCompare(b.host_name))
        }
        if (url.startsWith(`${base}/commands`)) {
          const saved = await response.clone().json() as typeof command
          commands = [...commands.filter(item => item.id !== saved.id), saved].sort((a, b) => a.title.localeCompare(b.title))
        }
      }
      return response
    }
    if (url === '/api/vcenters') return json(vcenters)
    if (url === `${base}/vcenters/${vc.id}/hosts`) return readHosts()
    if (url === `${base}/targets`) return readTargets()
    if (url === `${base}/commands`) return readCommands()
    if ([`${base}/ssh/credentials`, '/api/plugins/ssh/credentials'].includes(url)) return json(keys)
    if ([`${base}/ssh/connections`, '/api/plugins/ssh/connections'].includes(url)) return readSSH()
    return json({}, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('confirm', vi.fn(() => true))
})

afterEach(() => vi.unstubAllGlobals())

function renderDiagnostics() {
  return render(<DiagnosticsPanel />)
}

function click(name: string, root: Pick<typeof screen, 'getByRole'> = screen) {
  fireEvent.click(root.getByRole('button', { name, exact: true }))
}

function change(label: string, value: string, root: Pick<typeof screen, 'getByLabelText'> = screen) {
  fireEvent.change(root.getByLabelText(label, { exact: true }), { target: { value } })
}

function requests() {
  return fetchMock.mock.calls.map(([path, options]) => [
    options.method ?? 'GET', path, options.body ? JSON.parse(String(options.body)) : undefined,
  ])
}

function expectSshPaths(expected: string, excluded: string) {
  expect(requests()).toContainEqual(['GET', `${expected}/ssh/credentials`, undefined])
  expect(requests()).toContainEqual(['GET', `${expected}/ssh/connections`, undefined])
  expect(requests().filter(([, path]) => path.startsWith(`${excluded}/ssh/`))).toEqual([])
}

async function openExisting(title: string, formName: string) {
  fireEvent.click(await screen.findByLabelText(`${title}、ESXi`))
  const edit = screen.getByRole('button', { name: '変更・削除' })
  await waitFor(() => expect(edit).toBeEnabled())
  fireEvent.click(edit)
  const form = within(screen.getByRole('form', { name: formName }))
  if (formName === '実行の対象を変更') await waitForConnection(form)
  return form
}

async function addCommand() {
  fireEvent.click(await screen.findByRole('button', { name: 'コマンドを追加' }))
  const form = within(screen.getByRole('form', { name: 'コマンドを追加' }))
  change('名前', '状態を確認', form)
  change('コマンドの雛形', 'hostname', form)
  return form
}

async function openSSHConnection() {
  const open = await screen.findByRole('button', { name: '接続先を追加' })
  await waitFor(() => expect(open).toBeEnabled())
  fireEvent.click(open)
}

async function waitForConnection(form: ReturnType<typeof within>) {
  const choices = within(form.getByLabelText('診断用の SSH 接続先'))
  const option = await choices.findByRole('option', { name: /diagnostics@esxi\.example\.net/ })
  expect(option).toHaveValue(connection.id)
}

async function openUpload(secret = privateKey) {
  await openSSHConnection()
  change('鍵の用意方法', 'upload')
  fireEvent.change(screen.getByLabelText('既存の秘密鍵をアップロード'), {
    target: { files: [new File([secret], 'diagnostic-key')] },
  })
  click('選択した鍵を登録')
}

describe('診断用の SSH', () => {
  it('診断用 API で鍵を生成し、接続先を登録・変更してホスト鍵を取得・承認する', async () => {
    keys = []
    connections = []
    const ssh = `${base}/ssh`
    write = (path, method, body) => {
      if (method === 'POST' && path === `${ssh}/credentials`) {
        keys = [key]
        return json(key)
      }
      if (method === 'POST' && path === `${ssh}/connections`) {
        connections = [connection]
        return json(connection)
      }
      if (method === 'PUT' && path === `${ssh}/connections/ssh1`) {
        const updated = { ...connection, port: 2222, revision: 2 }
        connections = [updated]
        return json(updated)
      }
      if (method === 'POST' && path === `${ssh}/connections/ssh1/host-key`) {
        const updated = { ...connection, port: 2222, revision: 3, candidate_fingerprint: 'SHA256:confirmed' }
        connections = [updated]
        return json(updated)
      }
      if (method === 'POST' && path === `${ssh}/connections/ssh1/approve`) {
        expect(body).toEqual({ fingerprint: 'SHA256:confirmed', revision: 3 })
        const updated = { ...connection, port: 2222, revision: 4, approved: true, fingerprint: 'SHA256:confirmed' }
        connections = [updated]
        return json(updated)
      }
      return json({}, 405)
    }

    renderDiagnostics()
    await screen.findByRole('button', { name: 'コマンドを追加' })
    await openSSHConnection()
    click('アプリで鍵を生成')
    await screen.findByText('鍵を用意しました。公開鍵を管理者へ渡してください。')
    change('ホスト名', connection.host)
    change('SSH ユーザー名', connection.username)
    click('接続先を保存')

    const editConnection = await screen.findByRole('button', { name: '選択した接続先を変更' })
    fireEvent.click(await screen.findByText('管理者へ渡す公開鍵と登録依頼'))
    expect(screen.getByText(/Administrator ロールと Shell Access/)).toBeVisible()
    expect(screen.getByText(key.public_key)).toBeVisible()
    expect(screen.queryByText(/対象ログの読取権限/)).not.toBeInTheDocument()
    fireEvent.click(editConnection)
    change('SSH ポート', '2222')
    click('接続先を保存')
    await screen.findByText(/:2222 \/ diagnostics/)
    click('ホスト鍵を取得')
    expect(await screen.findByRole('button', { name: 'このホスト鍵を承認' })).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox', { name: /管理者から入手した指紋/ }))
    click('このホスト鍵を承認')
    await screen.findByText(/— 承認済み/)

    expectSshPaths(base, '/api/plugins')
    expect(requests()).toContainEqual(['POST', `${ssh}/credentials`, { name: '診断用 SSH 鍵' }])
    expect(requests()).toContainEqual(['POST', `${ssh}/connections`, {
      name: connection.host, host: connection.host, port: 22, username: connection.username, credential_id: key.id,
    }])
    expect(requests()).toContainEqual(['PUT', `${ssh}/connections/ssh1`, {
      name: connection.name, host: connection.host, port: 2222, username: connection.username, credential_id: key.id,
    }])
  })

  it('プラグインの SSH 部品はプラグイン用 API とログ収集の依頼文を使う', async () => {
    render(<SchemaFields schema={{ type: 'string', 'x-vea-widget': 'ssh-connection' }} value="ssh1" onChange={vi.fn()} vcenters={[]} />)
    fireEvent.click(await screen.findByText('管理者へ渡す公開鍵と登録依頼'))
    expect(screen.getByText(/対象ログの読取権限/)).toBeVisible()
    expectSshPaths('/api/plugins', base)
  })

  it('アップロードした秘密鍵を応答の余分な項目から表示せず、公開鍵だけを表示する', async () => {
    write = (_path, _method, body) => {
      expect(body).toEqual({ name: '診断用 SSH 鍵', private_key: privateKey })
      const response = { ...key, private_key: privateKey }
      keys = [response]
      return json(response)
    }
    renderDiagnostics()
    await openUpload()
    fireEvent.click(await screen.findByText('管理者へ渡す公開鍵と登録依頼'))
    expect(screen.getByText(key.public_key)).toBeVisible()
    expect(document.body).not.toHaveTextContent(testKeyFragment)
    expect(requests().filter(([, path]) => path.startsWith('/api/plugins/ssh/'))).toEqual([])
  })

  it('秘密鍵が公開鍵の項目に含まれた応答を受け付けない', async () => {
    write = () => json({ ...key, public_key: privateKey })
    renderDiagnostics()
    await openUpload()
    expect(await screen.findByRole('alert')).toHaveTextContent('秘密鍵を登録できませんでした。')
    expect(screen.queryByText('管理者へ渡す公開鍵と登録依頼')).not.toBeInTheDocument()
    expect(document.body).not.toHaveTextContent(testKeyFragment)
  })

  it('アップロードを断ったサーバーが秘密鍵をエラーに含めても表示しない', async () => {
    write = () => json({ detail: `入力のエラー: ${privateKey}` }, 422)
    renderDiagnostics()
    await openUpload()
    expect(await screen.findByRole('alert')).toHaveTextContent('秘密鍵を登録できませんでした。')
    expect(document.body).not.toHaveTextContent(testKeyFragment)
  })
})

describe('実行の対象', () => {
  it('vCenter の ESXi を選んで接続先を登録し、vCenter 自身へ変更して削除する', async () => {
    write = (_path, method, body) => json(method === 'DELETE' ? { ok: true } : {
      ...target, ...body as object, revision: method === 'PUT' ? 'updated' : 'created',
    })
    renderDiagnostics()
    fireEvent.click(await screen.findByRole('button', { name: '実行の対象を追加' }))
    const form = within(screen.getByRole('form', { name: '実行の対象を追加' }))
    change('vCenter', vc.id, form)
    click('ESXi 一覧を取得', form)
    await form.findByRole('option', { name: esxi.name })
    change('製品とホスト', `esxi:${esxi.id}`, form)
    await waitForConnection(form)
    change('診断用の SSH 接続先', connection.id, form)
    click('保存', form)

    const editor = await openExisting(esxi.name, '実行の対象を変更')
    change('製品とホスト', 'vcenter', editor)
    click('保存', editor)
    await screen.findByText('保存しました。')
    fireEvent.click(await screen.findByLabelText(`${vc.name}、vCenter`))
    click('変更・削除')
    click('削除', within(screen.getByRole('form', { name: '実行の対象を変更' })))
    await screen.findByText('実行の対象は未登録です。')

    const input = { product: 'esxi', host_moid: esxi.id, host_name: esxi.name, vcenter_id: vc.id, ssh_connection_id: connection.id }
    expect(requests()).toContainEqual(['GET', `${base}/vcenters/${vc.id}/hosts`, undefined])
    expect(requests()).toContainEqual(['POST', `${base}/targets`, input])
    expect(requests()).toContainEqual(['PUT', `${base}/targets/target1`, {
      ...input, product: 'vcenter', host_moid: null, host_name: vc.name, revision: 'created',
    }])
    expect(requests()).toContainEqual(['DELETE', `${base}/targets/target1?revision=updated`, undefined])
  })

  it('更新時の 409 では入力を保持し、読み直してから最新の revision で編集できる', async () => {
    targets = [target]
    write = () => {
      targets = [{ ...target, revision: 'latest', host_name: '別の管理者が変更' }]
      return json({ detail: '診断設定が変更されました。' }, 409, { 'X-VEA-Error-Code': 'diagnostic_setting_stale' })
    }
    renderDiagnostics()
    const form = await openExisting(target.host_name, '実行の対象を変更')
    change('製品とホスト', 'vcenter', form)
    click('保存', form)
    expect(await form.findByRole('alert')).toHaveTextContent('診断設定が変更されました。')
    expect(form.getByLabelText('製品とホスト')).toHaveValue('vcenter')
    expect(form.queryByRole('button', { name: '保存' })).not.toBeInTheDocument()
    expect(form.queryByRole('button', { name: '削除' })).not.toBeInTheDocument()
    expect(requests()).toContainEqual(['PUT', `${base}/targets/target1`, expect.objectContaining({ revision: 'original' })])

    click('編集を破棄して読み直す', form)
    expect(await screen.findByLabelText('別の管理者が変更、ESXi')).toBeInTheDocument()
    write = (_path, _method, body) => json({ ...target, ...body as object, host_name: '再編集済み', revision: 'saved' })
    const reloaded = await openExisting('別の管理者が変更', '実行の対象を変更')
    click('保存', reloaded)
    expect(await screen.findByLabelText('再編集済み、ESXi')).toBeInTheDocument()
    expect(requests()).toContainEqual(['PUT', `${base}/targets/target1`, expect.objectContaining({ revision: 'latest' })])
  })
})

describe('追加のコマンド', () => {
  it('API の種類から選んでコマンドを追加し、製品と説明を変更する', async () => {
    write = (_path, method, body) => json({ ...command, ...body as object, revision: method === 'POST' ? 'created' : 'updated' })
    renderDiagnostics()
    const form = await addCommand()
    click('引数を追加', form)
    const options = within(form.getByLabelText('引数 1 の種類')).getAllByRole<HTMLOptionElement>('option').slice(1)
    expect(options.map(option => option.value)).toEqual(parameterTypes)
    expect(options.map(option => option.textContent)).toEqual([
      'vmnic（例: vmnic0）', 'vmk（例: vmk0）', 'ipv4（例: 192.0.2.10）', 'device（例: naa.…、t10.…）',
    ])
    change('引数 1 の名前', 'nic', form)
    change('引数 1 の種類', 'vmnic', form)
    change('コマンドの雛形', 'example {{nic}}', form)
    click('保存', form)
    const editor = await openExisting('状態を確認', '追加のコマンドを変更')
    change('製品', 'vcenter', editor)
    change('説明', '変更した説明', editor)
    click('保存', editor)
    await screen.findByLabelText('状態を確認、vCenter')

    const input = { product: 'esxi', title: '状態を確認', description: '', template: 'example {{nic}}', param_definitions: [{ name: 'nic', type: 'vmnic' }] }
    expect(requests()).toContainEqual(['POST', `${base}/commands`, input])
    expect(requests()).toContainEqual(['PUT', `${base}/commands/command1`, {
      ...input, product: 'vcenter', description: '変更した説明', revision: 'created',
    }])
  })

  it('削除時の 409 では削除を再送せず、読み直した revision で削除できる', async () => {
    commands = [command]
    write = () => {
      commands = [{ ...command, revision: 'latest', title: '別の管理者が変更' }]
      return json({ detail: '診断設定が変更されました。' }, 409, { 'X-VEA-Error-Code': 'diagnostic_setting_stale' })
    }
    renderDiagnostics()
    const form = await openExisting(command.title, '追加のコマンドを変更')
    click('削除', form)
    expect(await form.findByRole('alert')).toHaveTextContent('診断設定が変更されました。')
    expect(form.queryByRole('button', { name: '削除' })).not.toBeInTheDocument()
    expect(requests().filter(([method]) => method === 'DELETE')).toEqual([
      ['DELETE', `${base}/commands/command1?revision=original`, undefined],
    ])

    click('編集を破棄して読み直す', form)
    const reloaded = await openExisting('別の管理者が変更', '追加のコマンドを変更')
    write = () => json({ ok: true })
    click('削除', reloaded)
    expect(await screen.findByText('追加のコマンドは未登録です。')).toBeInTheDocument()
    expect(requests()).toContainEqual(['DELETE', `${base}/commands/command1?revision=latest`, undefined])
  })

  it.each([
    ['control_character', null, '雛形に改行や制御文字'],
    ['undefined_parameter', 'Missing', '引数「Missing」が雛形の差し込み口に使われていますが、定義されていません。'],
    ['unused_parameter', 'nic', '引数「nic」が雛形で使われていません。'],
    ['dollar_prefix', 'nic', '差し込み口の直前に $'],
    ['backslash_prefix', 'nic', '差し込み口の直前にバックスラッシュ'],
    ['invalid_parameter_name', 'Invalid', '引数「Invalid」の名前は小文字の英字で始め'],
    ['duplicate_parameter', 'nic', '引数「nic」の名前が重複しています。'],
    ['unknown_parameter_type', 'nic', '引数「nic」の種類を一覧から'],
    ['too_many_parameters', null, '引数は8個まで'],
    ['unused_parameter', '', '引数が雛形で使われていません。'],
  ] as const)('登録を断った理由 %s を編集欄に表示する', async (reason, parameter, message) => {
    write = () => json({ detail: { reason, parameter } }, 422, { 'X-VEA-Error-Code': 'diagnostic_template_invalid' })
    renderDiagnostics()
    const form = await addCommand()
    click('保存', form)
    const alert = await form.findByRole('alert')
    expect(alert).toHaveTextContent(message)
    expect(alert).not.toHaveTextContent(reason)
    if (!parameter) expect(alert).not.toHaveTextContent('引数「')
    else expect(alert).toHaveTextContent(`引数「${parameter}」`)
    expect(form.getByLabelText('名前')).toHaveValue('状態を確認')
  })

  it('別の 422 は雛形の理由として表示しない', async () => {
    write = () => json({ detail: { reason: 'unused_parameter', parameter: 'nic' } }, 422)
    renderDiagnostics()
    const form = await addCommand()
    click('保存', form)
    expect(await form.findByRole('alert')).toHaveTextContent('入力内容を確認してください。')
  })

  it('引数を8個まで追加でき、1個削除すると再び追加できる', async () => {
    renderDiagnostics()
    const form = await addCommand()
    const add = form.getByRole('button', { name: '引数を追加' })
    for (let i = 0; i < 8; i += 1) fireEvent.click(add)
    expect(add).toBeDisabled()
    fireEvent.click(add)
    expect(form.getAllByLabelText(/引数 \d+ の名前/)).toHaveLength(8)
    click('引数 4 を削除', form)
    expect(add).toBeEnabled()
    fireEvent.click(add)
    expect(add).toBeDisabled()
  })
})

describe('SSH の一覧とプラグインの互換性', () => {
  const pluginSchema = { type: 'string', 'x-vea-widget': 'ssh-connection' }

  async function uploadFrom(scope: '診断' | 'プラグイン', secret: string) {
    if (scope === '診断') {
      renderDiagnostics()
      await openSSHConnection()
    } else {
      render(<SchemaFields schema={pluginSchema} value="" onChange={vi.fn()} vcenters={[]} />)
      click('接続先を追加・変更')
    }
    change('鍵の用意方法', 'upload')
    fireEvent.change(screen.getByLabelText('既存の秘密鍵をアップロード'), {
      target: { files: [new File([secret], 'fixture-key')] },
    })
    click('選択した鍵を登録')
  }

  const uploadCases = (['診断', 'プラグイン'] as const).flatMap(scope =>
    uploadKeys.map(pair => ({ scope, ...pair })),
  )

  it.each(uploadCases)('$scope は OpenSSH の $algorithm 秘密鍵を登録できる', async ({ scope, algorithm, privateKey, publicKey }) => {
    if (algorithm !== 'ssh-ed25519') {
      // 旧判定が成功応答を誤って拒否する組を固定する。
      expect(privateKey.split('\n').some(line => line.length >= 24 && publicKey.includes(line))).toBe(true)
    }
    const saved = { ...key, id: 'uploaded-key', public_key: publicKey }
    write = (_path, _method, body) => {
      expect(body).toEqual(expect.objectContaining({ private_key: privateKey }))
      keys = [saved]
      return json(saved)
    }
    await uploadFrom(scope, privateKey)
    await screen.findByText('鍵を用意しました。公開鍵を管理者へ渡してください。')
    fireEvent.click(await screen.findByText('管理者へ渡す公開鍵と登録依頼'))
    expect(screen.getByText(publicKey.trim())).toBeVisible()
    expect(document.body).not.toHaveTextContent(opensshPrivateKeyBegin)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it.each(uploadCases.filter(pair => pair.algorithm !== 'ssh-ed25519'))(
    '$scope はエラー応答の $algorithm の公開鍵断片を伏せない', async ({ scope, privateKey, publicKey }) => {
      const publicLine = privateKey.split('\n').find(line => line.length >= 24 && publicKey.includes(line))
      expect(publicLine).toBeDefined()
      const detail = `公開鍵を確認してください。 ${publicLine}`
      write = () => json({ detail }, 422)
      await uploadFrom(scope, privateKey)
      expect(await screen.findByRole('alert')).toHaveTextContent(detail)
    },
  )

  it.each(['診断', 'プラグイン'] as const)('%s は形式に合っても秘密鍵の見出しを含む成功応答を表示しない', async scope => {
    write = () => json({ ...key, public_key: `ssh-rsa PUBLIC ${opensshPrivateKeyBegin}` })
    await uploadFrom(scope, privateKey)
    expect(await screen.findByRole('alert')).toHaveTextContent('秘密鍵を登録できませんでした。')
    expect(screen.queryByText('管理者へ渡す公開鍵と登録依頼')).not.toBeInTheDocument()
  })


  it.each(['診断', 'プラグイン'] as const)('%s は秘密鍵の本文だけを返した成功応答を公開鍵として表示しない', async scope => {
    const secret = uploadKeys[0].privateKey
    write = () => json({ ...key, public_key: secret.trim().split('\n').slice(1, -1).join('') })
    await uploadFrom(scope, secret)
    expect(await screen.findByRole('alert')).toHaveTextContent('秘密鍵を登録できませんでした。')
    expect(screen.queryByText('管理者へ渡す公開鍵と登録依頼')).not.toBeInTheDocument()
  })

  it.each(uploadCases)('$scope は種類を前に付けた $algorithm の秘密鍵の本文を公開鍵として表示しない', async ({ scope, algorithm, privateKey }) => {
    const body = privateKey.trim().split('\n').slice(1, -1).join('')
    write = () => json({ ...key, public_key: `${algorithm} ${body}` })
    await uploadFrom(scope, privateKey)
    expect(await screen.findByRole('alert')).toHaveTextContent('秘密鍵を登録できませんでした。')
    expect(screen.queryByText('管理者へ渡す公開鍵と登録依頼')).not.toBeInTheDocument()
    expect(document.body).not.toHaveTextContent(body.slice(0, 40))
  })

  it.each(uploadCases)('$scope は「\\n」の文字でつないだ $algorithm の秘密鍵の本文をエラーに出さない', async ({ scope, privateKey }) => {
    const lines = privateKey.trim().split('\n').slice(1, -1)
    // 各行の前に「\n」の文字が付くと、正規化しなければ断片の頭に n が付いて本文と一致しない。
    write = () => json({ detail: `入力のエラー: ${lines.map(line => `\\n${line}`).join('')}` }, 422)
    await uploadFrom(scope, privateKey)
    expect(await screen.findByRole('alert')).toHaveTextContent('秘密鍵を登録できませんでした。')
    expect(document.body).not.toHaveTextContent(lines[lines.length - 1])
  })

  it.each(['診断', 'プラグイン'] as const)('%s は PEM 形式の秘密鍵の本文の 1 行をエラーに出さない', async scope => {
    const pem = generateKeyPairSync('rsa', {
      modulusLength: 2048,
      privateKeyEncoding: { type: 'pkcs1', format: 'pem' },
      publicKeyEncoding: { type: 'spki', format: 'pem' },
    }).privateKey
    const line = pem.trim().split('\n')[3]
    write = () => json({ detail: `入力のエラー: ${line}` }, 422)
    await uploadFrom(scope, pem)
    expect(await screen.findByRole('alert')).toHaveTextContent('秘密鍵を登録できませんでした。')
    expect(document.body).not.toHaveTextContent(line)
  })

  it('プラグインの鍵名・接続先の説明・公開鍵の依頼文を維持する', async () => {
    render(<SchemaFields schema={pluginSchema} value={connection.id} onChange={vi.fn()} vcenters={[]} />)
    fireEvent.click(await screen.findByText('管理者へ渡す公開鍵と登録依頼'))
    expect(screen.getByText('対象サーバーでSSHを有効化し、SSHユーザー「diagnostics」へ次の公開鍵を登録してください。対象ログの読取権限も必要です。登録後、SSHホスト鍵のSHA-256指紋を導入担当者へ別経路でお知らせください。')).toBeVisible()
    click('接続先を追加・変更')
    expect(screen.getByText('収集中の接続先を変える場合は、新しい接続先を登録してテスト後に適用します。')).toBeVisible()
    expect(screen.getByText('SSH接続を登録')).toBeVisible()
    expect(screen.getByLabelText('SSHポート')).toBeVisible()
    expect(screen.getByLabelText('SSHユーザー名')).toBeVisible()
    change('鍵の用意方法', 'generate')
    expect(screen.getByLabelText('鍵の名前')).toHaveValue('ログ収集用SSH鍵')
  })

  it('プラグインは既存の鍵の一覧と生成結果を従来の形式で受け取る', async () => {
    const legacyKey = { ...key, public_key: '従来の登録済み公開鍵' }
    const generated = { id: 'key2', name: '生成した鍵', public_key: '従来の生成応答' }
    keys = [legacyKey]
    write = () => {
      keys = [legacyKey, generated]
      return json(generated)
    }
    render(<SchemaFields schema={pluginSchema} value={connection.id} onChange={vi.fn()} vcenters={[]} />)
    expect(await screen.findByText(legacyKey.public_key)).toBeInTheDocument()
    click('接続先を追加・変更')
    change('鍵の用意方法', 'generate')
    expect(screen.getByRole('button', { name: 'アプリで鍵を生成' })).not.toHaveClass('diagnostic-grid-action')
    click('アプリで鍵を生成')
    expect(await screen.findByText(generated.public_key)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it.each([
    [401, '認証情報を送ってください。', 'ログインの有効期限が切れました。再度ログインしてください。'],
    [403, '権限エラーです。', 'この操作を行う権限がありません。'],
    [500, 'サーバー内部の理由', 'リクエストに失敗しました。時間をおいて再度お試しください。'],
    [422, '登録できる鍵の上限に達しました。', '登録できる鍵の上限に達しました。'],
    [422, privateKey, '秘密鍵を登録できませんでした。'],
  ])('プラグインのアップロード拒否 %i を従来の文言で表示し、鍵の反射を除く', async (status, detail, message) => {
    write = () => json({ detail }, status)
    render(<SchemaFields schema={pluginSchema} value="" onChange={vi.fn()} vcenters={[]} />)
    fireEvent.click(await screen.findByRole('button', { name: '接続先を追加・変更' }))
    change('鍵の用意方法', 'upload')
    fireEvent.change(screen.getByLabelText('既存の秘密鍵をアップロード'), {
      target: { files: [new File([privateKey], 'plugin-key')] },
    })
    click('選択した鍵を登録')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(message)
    expect(alert).not.toHaveAttribute('class')
    expect(document.body).not.toHaveTextContent(testKeyFragment)
    expect(screen.getByRole('button', { name: '選択した鍵を登録' })).toBeEnabled()
  })

  it('プラグインは接続先の保存応答を検査せずに選択する', async () => {
    write = () => json({ id: connection.id })
    const onChange = vi.fn()
    render(<SchemaFields schema={pluginSchema} value={connection.id} onChange={onChange} vcenters={[]} />)
    await screen.findByRole('option', { name: `${connection.name} (${connection.host})` })
    click('接続先を追加・変更')
    click('接続先を保存')
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(connection.id))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('プラグインは失敗・サイズ超過・方式の変更・編集し直しで選択したファイルを保持する', async () => {
    render(<SchemaFields schema={pluginSchema} value="" onChange={vi.fn()} vcenters={[]} />)
    click('接続先を追加・変更')
    change('鍵の用意方法', 'upload')
    fireEvent.change(screen.getByLabelText('既存の秘密鍵をアップロード'), {
      target: { files: [new File(['x'.repeat(32769)], 'oversized-key')] },
    })
    click('選択した鍵を登録')
    expect(await screen.findByRole('alert')).toHaveTextContent('32KiB以下の秘密鍵を選択してください。')
    expect(screen.getByRole('button', { name: '選択した鍵を登録' })).toBeEnabled()
    change('鍵の用意方法', 'generate')
    change('鍵の用意方法', 'upload')
    expect(screen.getByRole('button', { name: '選択した鍵を登録' })).toBeEnabled()
    click('接続先を追加・変更')
    click('接続先を追加・変更')
    expect(screen.getByRole('button', { name: '選択した鍵を登録' })).toBeEnabled()
    expect(requests().some(([method]) => method === 'POST')).toBe(false)
  })

  it('プラグインはアップロード成功時に選択したファイルを消す', async () => {
    write = () => json(key)
    render(<SchemaFields schema={pluginSchema} value="" onChange={vi.fn()} vcenters={[]} />)
    click('接続先を追加・変更')
    change('鍵の用意方法', 'upload')
    fireEvent.change(screen.getByLabelText('既存の秘密鍵をアップロード'), {
      target: { files: [new File([privateKey], 'plugin-key')] },
    })
    click('選択した鍵を登録')
    await screen.findByText('鍵を用意しました。公開鍵を管理者へ渡してください。')
    change('鍵の用意方法', 'generate')
    change('鍵の用意方法', 'upload')
    expect(screen.getByRole('button', { name: '選択した鍵を登録' })).toBeDisabled()
  })

  it('プラグインは一覧の公開鍵欄に混入した秘密鍵を公開しない', async () => {
    keys = [{ ...key, public_key: privateKey }]
    render(<SchemaFields schema={pluginSchema} value={connection.id} onChange={vi.fn()} vcenters={[]} />)
    await screen.findByRole('option', { name: `${connection.name} (${connection.host})` })
    expect(screen.queryByText('管理者へ渡す公開鍵と登録依頼')).not.toBeInTheDocument()
    expect(document.body).not.toHaveTextContent(testKeyFragment)
  })

  it('診断は一覧の応答で公開鍵の形式を検査する', async () => {
    keys = [{ ...key, public_key: '公開鍵の形式に合わない値' }]
    renderDiagnostics()
    const section = within(screen.getByRole('region', { name: 'SSH の鍵と接続先' }))
    expect(await section.findByRole('alert')).toBeInTheDocument()
    expect(section.getByRole('button', { name: '接続先を追加' })).toBeDisabled()
  })

  it('診断はアップロード成功の応答でも公開鍵の形式を検査する', async () => {
    write = () => json({ ...key, public_key: '公開鍵の形式に合わない値' })
    renderDiagnostics()
    await openUpload()
    const section = within(screen.getByRole('region', { name: 'SSH の鍵と接続先' }))
    expect(await section.findByRole('alert')).toBeInTheDocument()
    expect(section.queryByText('管理者へ渡す公開鍵と登録依頼')).not.toBeInTheDocument()
  })

  const { privateKey: realPrivateKey, publicKey: realPublicKey } = uploadKeys[0]
  const privateBody = realPrivateKey.trim().split('\n').slice(1, -1).join('')
  const privateFragment = realPrivateKey.trim().split('\n').slice(1, -1)
    .map(line => line.slice(2, 30))
    .findLast(fragment => fragment.length === 28 && !realPublicKey.includes(fragment))!
  it.each([
    ['秘密鍵の見出し', '選択したファイルの中身', `独立した秘密鍵の印: ${opensshPrivateKeyBegin}`],
    ['秘密鍵の本文の断片', realPrivateKey, `秘密鍵の一部: ${privateFragment}`],
    ['秘密鍵の本文全体', realPrivateKey, `鍵の本文: ${privateBody.match(/.{1,20}/g)!.join(' ')}`],
  ])('診断は応答エラーに含まれる %s を表示しない', async (_name, file, detail) => {
    write = () => json({ detail }, 422)
    renderDiagnostics()
    await openUpload(file)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('秘密鍵を登録できませんでした。')
    expect(alert).not.toHaveTextContent(detail)
  })

  it('診断の鍵生成・登録ボタンは接続先の保存と同じ配置にする', async () => {
    renderDiagnostics()
    await openSSHConnection()
    change('鍵の用意方法', 'generate')
    expect(screen.getByRole('button', { name: 'アプリで鍵を生成' })).toHaveClass('diagnostic-grid-action')
    change('鍵の用意方法', 'upload')
    expect(screen.getByRole('button', { name: '選択した鍵を登録' })).toHaveClass('diagnostic-grid-action')
  })

  it('診断は 32 KiB 超過時にファイル入力欄を空にする', async () => {
    renderDiagnostics()
    await openSSHConnection()
    change('鍵の用意方法', 'upload')
    const input = screen.getByLabelText<HTMLInputElement>('既存の秘密鍵をアップロード')
    const clearInput = vi.spyOn(input, 'value', 'set')
    fireEvent.change(input, { target: { files: [new File(['x'.repeat(32769)], 'oversized-key')] } })
    click('選択した鍵を登録')
    expect(await screen.findByRole('alert')).toHaveTextContent('32 KiB 以下の秘密鍵を選択してください。')
    expect(clearInput).toHaveBeenCalledWith('')
    expect(screen.getByRole('button', { name: '選択した鍵を登録' })).toBeDisabled()
    expect(requests().some(([method]) => method === 'POST')).toBe(false)
    clearInput.mockRestore()
  })

  it('SSH の設定を取得中または取得に失敗したら古いホスト鍵を操作できない', async () => {
    connections = [{ ...connection, candidate_fingerprint: 'SHA256:old' }]
    renderDiagnostics()
    await screen.findByRole('option', { name: `${connection.name}（${connection.host}）` })
    change('登録済みの SSH 接続先', connection.id)
    const checkbox = screen.getByRole('checkbox', { name: /管理者から入手した指紋/ })
    fireEvent.click(checkbox)
    expect(checkbox).toBeChecked()
    let finish!: (value: Response) => void
    readSSH = () => new Promise(resolve => { finish = resolve })
    click('SSH の設定を再取得')
    expect(checkbox).toBeDisabled()
    await act(async () => finish(json({ detail: 'SSH の設定を取得できません。' }, 422)))
    expect(await screen.findByRole('alert')).toHaveTextContent('SSH の設定を取得できません。')
    expect(checkbox).toBeDisabled()
    readSSH = () => json([{ ...connection, revision: 2, candidate_fingerprint: 'SHA256:new' }])
    click('SSH の設定を再取得')
    expect(await screen.findByText('SHA256:new')).toBeVisible()
    expect(checkbox).toBeEnabled()
    expect(checkbox).not.toBeChecked()
  })

  it('鍵の用意方法を切り替えると選択済みのファイルを破棄する', async () => {
    renderDiagnostics()
    await openSSHConnection()
    change('鍵の用意方法', 'upload')
    fireEvent.change(screen.getByLabelText('既存の秘密鍵をアップロード'), {
      target: { files: [new File([privateKey], 'diagnostic-key')] },
    })
    expect(screen.getByRole('button', { name: '選択した鍵を登録' })).toBeEnabled()
    change('鍵の用意方法', 'generate')
    change('鍵の用意方法', 'upload')
    expect(screen.getByRole('button', { name: '選択した鍵を登録' })).toBeDisabled()
  })

  it('SSH の 409 のあと一覧を読み直し、新しい指紋と revision で照合し直せる', async () => {
    connections = [{ ...connection, candidate_fingerprint: 'SHA256:old' }]
    write = () => {
      connections = [{ ...connection, revision: 2, candidate_fingerprint: 'SHA256:new' }]
      return json({ detail: 'ホスト鍵の取得をやり直してください。' }, 409)
    }
    renderDiagnostics()
    await screen.findByRole('option', { name: `${connection.name}（${connection.host}）` })
    change('登録済みの SSH 接続先', connection.id)
    expect(screen.getByText('SHA256:old')).toBeVisible()
    fireEvent.click(screen.getByRole('checkbox', { name: /管理者から入手した指紋/ }))
    click('このホスト鍵を承認')
    expect(await screen.findByRole('alert')).toHaveTextContent('ホスト鍵の取得をやり直してください。')
    expect(screen.getByRole('button', { name: 'このホスト鍵を承認' })).toBeDisabled()
    click('SSH の設定を再取得')
    expect(await screen.findByText('SHA256:new')).toBeVisible()
    expect(screen.queryByText('SHA256:old')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'このホスト鍵を承認' })).toBeDisabled()
    expect(requests().filter(([, path]) => path === `${base}/ssh/connections`)).toHaveLength(2)
    write = (_path, _method, body) => {
      expect(body).toEqual({ fingerprint: 'SHA256:new', revision: 2 })
      return json({ ...connection, revision: 3, approved: true, fingerprint: 'SHA256:new', candidate_fingerprint: 'SHA256:new' })
    }
    fireEvent.click(screen.getByRole('checkbox', { name: /管理者から入手した指紋/ }))
    click('このホスト鍵を承認')
    expect(await screen.findByText(/— 承認済み/)).toBeVisible()
  })
})

describe('診断の設定のエラーと操作', () => {
  it('診断の設定にアカウントの強い権限と用途の分離、コマンドの注意を表示する', () => {
    renderDiagnostics()
    expect(screen.getByText(/診断用のアカウントは強い権限を持ちます。/)).toBeVisible()
    expect(screen.getByText(/ログ収集とは別のアカウントと鍵を使用してください。/)).toBeVisible()
    expect(screen.getByText('追加のコマンドが読み取り専用かどうかは本体では確かめません。')).toBeVisible()
  })

  it('対象が重複した 409 は入力を残し、選び直して保存できる', async () => {
    targets = [target]
    write = () => json({ detail: '対象が重複しています。' }, 409, { 'X-VEA-Error-Code': 'diagnostic_target_duplicate' })
    renderDiagnostics()
    const form = await openExisting(target.host_name, '実行の対象を変更')
    change('製品とホスト', 'vcenter', form)
    click('保存', form)
    expect(await form.findByRole('alert')).toHaveTextContent('この vCenter・ESXi には実行の対象がすでにあります。')
    expect(form.getByLabelText('製品とホスト')).toHaveValue('vcenter')
    expect(form.getByRole('button', { name: '保存' })).toBeEnabled()
    expect(form.queryByRole('button', { name: '編集を破棄して読み直す' })).not.toBeInTheDocument()
    click('ESXi 一覧を取得', form)
    await form.findByRole('option', { name: esxi.name })
    change('製品とホスト', `esxi:${esxi.id}`, form)
    write = () => json({ ...target, revision: 'corrected' })
    click('保存', form)
    await screen.findByText('保存しました。')
    expect(requests()).toContainEqual(['PUT', `${base}/targets/target1`, expect.objectContaining({ host_moid: esxi.id, revision: 'original' })])
  })

  it.each(['vCenter', 'SSH 接続先'])('参照先の %s を失ったら、入力を保持しながら両方の一覧を読み直す', async missing => {
    const detail = '選んだ vCenter または SSH 接続先が削除されました。一覧を読み直して選び直してください。'
    targets = [target]
    write = () => json({ detail }, 409, { 'X-VEA-Error-Code': 'diagnostic_reference_missing' })
    renderDiagnostics()
    const form = await openExisting(target.host_name, '実行の対象を変更')
    change('製品とホスト', 'vcenter', form)
    click('保存', form)
    expect(await form.findByRole('alert')).toHaveTextContent(detail)
    expect(form.getByLabelText('vCenter')).toHaveValue(vc.id)
    expect(form.getByLabelText('製品とホスト')).toHaveValue('vcenter')
    expect(form.getByLabelText('診断用の SSH 接続先')).toHaveValue(connection.id)

    if (missing === 'vCenter') {
      vcenters = [{ ...vc, id: 'new-vc', name: '新しい vCenter' }]
      targets = []
    } else {
      connections = [{ ...connection, id: 'new-ssh', name: '新しい SSH' }]
    }
    click('一覧を読み直す', form)
    await waitFor(() => expect(form.queryByRole('alert')).not.toBeInTheDocument())
    for (const path of [`${base}/targets`, '/api/vcenters', `${base}/ssh/connections`]) {
      expect(requests().filter(([method, url]) => method === 'GET' && url === path)).toHaveLength(2)
    }
    if (missing === 'vCenter') {
      expect(form.getByLabelText('vCenter')).toHaveValue('')
      expect(form.queryByLabelText('製品とホスト')).not.toBeInTheDocument()
      expect(form.getByLabelText('診断用の SSH 接続先')).toHaveValue(connection.id)
      change('vCenter', 'new-vc', form)
      expect(form.getByLabelText('製品とホスト')).toHaveValue('')
    } else {
      expect(form.getByLabelText('vCenter')).toHaveValue(vc.id)
      expect(form.getByLabelText('製品とホスト')).toHaveValue('vcenter')
      expect(form.getByLabelText('診断用の SSH 接続先')).toHaveValue('')
      expect(screen.getByRole('option', { name: `新しい SSH（${connection.host}）` })).toBeInTheDocument()
    }
    expect(form.getByRole('button', { name: '保存' })).toBeDisabled()
  })

  it.each(['vCenter', 'SSH 接続先'])('一方の読み直しに失敗しても、消えた %s の選択は復活しない', async missing => {
    const detail = '選んだ vCenter または SSH 接続先が削除されました。一覧を読み直して選び直してください。'
    targets = [target]
    write = () => json({ detail }, 409, { 'X-VEA-Error-Code': 'diagnostic_reference_missing' })
    renderDiagnostics()
    const form = await openExisting(target.host_name, '実行の対象を変更')
    click('保存', form)
    expect(await form.findByRole('alert')).toHaveTextContent(detail)

    if (missing === 'vCenter') {
      vcenters = []
      readSSH = () => json({ detail: 'SSH の取得に失敗しました。' }, 422)
    } else {
      connections = []
      readTargets = () => json({ detail: '対象の取得に失敗しました。' }, 422)
    }
    const retry = form.getByRole('button', { name: '一覧を読み直す' })
    click('一覧を読み直す', form)
    await waitFor(() => expect(retry).toBeEnabled())
    expect(form.getByRole('alert')).toHaveTextContent(detail)

    vcenters = [vc]
    connections = [connection]
    readTargets = () => json(targets)
    readSSH = () => json(connections)
    fireEvent.click(retry)
    await waitFor(() => expect(form.queryByRole('alert')).not.toBeInTheDocument())
    expect(form.getByLabelText(missing === 'vCenter' ? 'vCenter' : '診断用の SSH 接続先')).toHaveValue('')
    if (missing === 'vCenter') {
      change('vCenter', vc.id, form)
      expect(form.getByLabelText('製品とホスト')).toHaveValue('')
    }
  })

  it('保存時の 404 を削除済みとして扱い、編集中の設定の再送を止める', async () => {
    commands = [command]
    write = () => {
      commands = []
      return json({ detail: '診断設定が見つかりません。' }, 404)
    }
    renderDiagnostics()
    const form = await openExisting(command.title, '追加のコマンドを変更')
    click('保存', form)
    expect(await form.findByRole('alert')).toHaveTextContent('この設定は削除されました。')
    expect(form.queryByRole('button', { name: '保存' })).not.toBeInTheDocument()
    click('編集を破棄して読み直す', form)
    expect(await screen.findByText('追加のコマンドは未登録です。')).toBeVisible()
  })

  it('削除の確認をキャンセルすると送信せず、編集中の内容を保持する', async () => {
    commands = [command]
    vi.stubGlobal('confirm', vi.fn(() => false))
    renderDiagnostics()
    const form = await openExisting(command.title, '追加のコマンドを変更')
    change('説明', '編集中の説明', form)
    click('削除', form)
    expect(confirm).toHaveBeenCalledWith('この設定を削除しますか？')
    expect(requests().some(([method]) => method === 'DELETE')).toBe(false)
    expect(form.getByLabelText('説明')).toHaveValue('編集中の説明')
  })

  it('選べる接続先がない間は対象の保存ボタンを無効にする', async () => {
    connections = []
    renderDiagnostics()
    fireEvent.click(await screen.findByRole('button', { name: '実行の対象を追加' }))
    const form = within(screen.getByRole('form', { name: '実行の対象を追加' }))
    change('vCenter', vc.id, form)
    change('製品とホスト', 'vcenter', form)
    expect(form.getByRole('button', { name: '保存' })).toBeDisabled()
    expect(requests().some(([method]) => method === 'POST')).toBe(false)
  })

  it('無効な vCenter は新規の実行の対象の候補から除く', async () => {
    vcenters = [vc, { ...vc, id: 'disabled', name: '無効な vCenter', is_enabled: false }]
    renderDiagnostics()
    fireEvent.click(await screen.findByRole('button', { name: '実行の対象を追加' }))
    expect(screen.getByRole('option', { name: vc.name })).toBeVisible()
    expect(screen.queryByRole('option', { name: /無効な vCenter/ })).not.toBeInTheDocument()
  })

  it.each(['コマンドを追加', '実行の対象を追加'])('%s のキャンセルと保存後は追加ボタンにフォーカスを戻す', async (name) => {
    write = path => json(path.endsWith('/commands') ? command : target, 201)
    renderDiagnostics()
    const open = await screen.findByRole('button', { name })
    fireEvent.click(open)
    click('キャンセル', within(screen.getByRole('form', { name })))
    expect(screen.getByRole('button', { name })).toHaveFocus()

    fireEvent.click(screen.getByRole('button', { name }))
    const form = within(screen.getByRole('form', { name }))
    if (name === 'コマンドを追加') {
      change('名前', command.title, form)
      change('コマンドの雛形', command.template, form)
    } else {
      change('vCenter', vc.id, form)
      change('製品とホスト', 'vcenter', form)
      await waitForConnection(form)
      change('診断用の SSH 接続先', connection.id, form)
    }
    click('保存', form)
    await screen.findByText('保存しました。')
    expect(screen.getByRole('button', { name })).toHaveFocus()
  })

  it('閉じる・保存・削除のあとに開いたボタンまたは見出しへフォーカスを戻す', async () => {
    commands = [command]
    write = (_path, method) => json(method === 'DELETE' ? { ok: true } : { ...command, revision: 'updated' })
    renderDiagnostics()
    const heading = screen.getByRole('heading', { name: '追加のコマンド' })
    const form = await openExisting(command.title, '追加のコマンドを変更')
    const edit = screen.getByRole('button', { name: '変更・削除' })
    expect(screen.getByRole('form', { name: '追加のコマンドを変更' })).toHaveFocus()
    click('キャンセル', form)
    expect(edit).toHaveFocus()

    fireEvent.click(edit)
    click('保存', formAfterOpening())
    await screen.findByText('保存しました。')
    expect(edit).toHaveFocus()

    fireEvent.click(edit)
    click('削除', formAfterOpening())
    await screen.findByText('削除しました。')
    expect(heading).toHaveFocus()

    function formAfterOpening() {
      return within(screen.getByRole('form', { name: '追加のコマンドを変更' }))
    }
  })

  it('SSH の一覧が読み込み中・失敗・0件のときに別々の案内を出す', async () => {
    targets = [target]
    let finish!: (value: Response) => void
    readSSH = () => new Promise(resolve => { finish = resolve })
    renderDiagnostics()
    fireEvent.click(await screen.findByRole('button', { name: '実行の対象を追加' }))
    const form = within(screen.getByRole('form', { name: '実行の対象を追加' }))
    const loading = form.getByText('SSH 接続先を読み込み中です…')
    expect(loading).toBeVisible()
    expect(loading).not.toHaveClass('diagnostic-wide')
    expect(form.queryByText(/接続先を登録してください/)).not.toBeInTheDocument()
    expect(screen.getByText(/SSH 接続先を取得中/)).toBeVisible()
    await act(async () => finish(json({ detail: '取得に失敗しました。' }, 422)))
    expect(await form.findByText(/SSH 接続先の取得に失敗しました/)).toBeVisible()
    expect(form.queryByText(/接続先を登録してください/)).not.toBeInTheDocument()
    expect(screen.getByText(/· SSH 接続先の取得に失敗/)).toBeVisible()

    readSSH = () => json([])
    click('SSH の設定を再取得')
    expect(await form.findByText(/接続先を登録してください/)).toBeVisible()
    expect(screen.getByText(/SSH 接続先を確認できません/)).toBeVisible()
  })

  it('ESXi 一覧の取得に失敗したらサーバーの理由を表示する', async () => {
    readHosts = () => json({ detail: 'vCenter の接続先のアドレスが許可されていません。' }, 422)
    renderDiagnostics()
    fireEvent.click(await screen.findByRole('button', { name: '実行の対象を追加' }))
    const form = within(screen.getByRole('form', { name: '実行の対象を追加' }))
    change('vCenter', vc.id, form)
    click('ESXi 一覧を取得', form)
    expect(await form.findByRole('alert')).toHaveTextContent('vCenter の接続先のアドレスが許可されていません。')
  })

  it.each([
    [422, 'ESXi一覧を取得できません。ホスト名を手入力してください。'],
    [403, '利用できない理由です。'],
    [404, '機能が無効です。'],
  ])('ESXi 一覧の失敗 %i は画面で使える操作を案内する', async (status, detail) => {
    readHosts = () => json({ detail }, status)
    renderDiagnostics()
    fireEvent.click(await screen.findByRole('button', { name: '実行の対象を追加' }))
    const form = within(screen.getByRole('form', { name: '実行の対象を追加' }))
    change('vCenter', vc.id, form)
    click('ESXi 一覧を取得', form)
    const alert = await form.findByRole('alert')
    expect(alert).toHaveTextContent('ESXi 一覧を取得できません。vCenter の接続設定・参照権限を確認し、再試行してください。')
    expect(alert).not.toHaveTextContent(detail)
  })

  it('対象とコマンドの一覧エラーをそれぞれの区画に保持する', async () => {
    readTargets = () => json({ detail: '診断の対象一覧を取得できません。' }, 422)
    readCommands = () => json({ detail: '診断のコマンド一覧を取得できません。' }, 422)
    renderDiagnostics()
    const targetsSection = within(screen.getByRole('region', { name: '実行の対象' }))
    const commandsRegion = screen.getByRole('region', { name: '追加のコマンド' })
    const commandsSection = within(commandsRegion)
    expect(await targetsSection.findByRole('alert')).toHaveTextContent('診断の対象一覧を取得できません。')
    expect(await commandsSection.findByRole('alert')).toHaveTextContent('診断のコマンド一覧を取得できません。')
    expect(commandsRegion).toHaveClass('panel')

    readCommands = () => json({ custom: [command], builtin: [], parameter_types: parameterTypes })
    click('コマンドの一覧を再取得', commandsSection)
    expect(await commandsSection.findByLabelText(`${command.title}、ESXi`)).toBeInTheDocument()
    expect(commandsSection.queryByRole('alert')).not.toBeInTheDocument()
    expect(targetsSection.getByRole('alert')).toHaveTextContent('診断の対象一覧を取得できません。')
  })

  it('雛形は1行の入力欄にし、追加したコマンドはサーバーの名前順で表示する', async () => {
    commands = [{ ...command, title: 'z-command' }]
    write = () => json({ ...command, id: 'alpha', title: 'a-command' }, 201)
    renderDiagnostics()
    const form = await addCommand()
    expect(form.getByLabelText('コマンドの雛形').tagName).toBe('INPUT')
    expect(form.getByRole('button', { name: '保存' })).toHaveClass('btn--filled')
    change('名前', 'a-command', form)
    click('保存', form)
    await screen.findByText('保存しました。')
    expect(screen.getAllByLabelText(/-command、ESXi/).map(row => row.getAttribute('aria-label')))
      .toEqual(['a-command、ESXi', 'z-command、ESXi'])
  })
})
