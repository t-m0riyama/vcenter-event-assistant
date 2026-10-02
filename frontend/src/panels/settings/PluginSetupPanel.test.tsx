import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PluginSetupPanel, { SchemaFields } from './PluginSetupPanel'
import { apiGet, apiPost, apiPut } from '../../api'

vi.mock('../../api', () => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiPut: vi.fn(), apiDelete: vi.fn() }))
const get = vi.mocked(apiGet), post = vi.mocked(apiPost), put = vi.mocked(apiPut)
const base = '/api/plugins/collectors/example.setup'
const definition = {
  schema: { type: 'object', properties: { sensor: { type: 'string', title: 'センサー', default: 'board' } } },
  unavailable_reason: null, env_locked_fields: [],
  actions: [{ id: 'test', title: '接続テスト', required_for_enable: true }], draft: null,
}
const vcs = [{ id: 'vc1', name: '運用vCenter', host: 'vc.example.net', is_enabled: true }]

beforeEach(() => {
  vi.resetAllMocks()
  get.mockImplementation(async path => path.endsWith('/configuration') ? definition : vcs)
})

describe('共通のプラグイン導入画面', () => {
  it('必須テストが成功するまで適用せず、編集後は再テストを要求する', async () => {
    const saved = { config_values: { sensor: 'board' }, revision: 2, tests: {} }
    put.mockResolvedValue(saved)
    post.mockResolvedValue({ ok: true, checks: [{ id: 'connection', label: '接続', ok: true, message: '成功' }], samples: [{ text: '<script>alert(1)</script>' }], warnings: [], elapsed_seconds: 1, draft: { ...saved, tests: { test: { ok: true } } } })
    const applied = vi.fn().mockResolvedValue(undefined)
    render(<PluginSetupPanel pluginId="example.setup" onApplied={applied} />)
    fireEvent.click(await screen.findByRole('button', { name: '次へ' }))
    await screen.findByRole('button', { name: '接続テスト' })
    expect(screen.queryByRole('button', { name: '収集を開始' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '接続テスト' }))
    await screen.findByRole('button', { name: '収集を開始' })
    expect(post).toHaveBeenCalledWith(`${base}/draft/actions/test`, { revision: 2 })
    expect(screen.getByText('text: <script>alert(1)</script>')).toBeInTheDocument()
    expect(document.querySelector('script')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '戻る' }))
    fireEvent.change(screen.getByLabelText('センサー'), { target: { value: 'changed' } })
    expect(screen.queryByRole('button', { name: '収集を開始' })).not.toBeInTheDocument()
    expect(applied).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '次へ' }))
    fireEvent.click(await screen.findByRole('button', { name: '接続テスト' }))
    fireEvent.click(await screen.findByRole('button', { name: '収集を開始' }))
    await waitFor(() => expect(applied).toHaveBeenCalledOnce())
    expect(post).toHaveBeenCalledWith(`${base}/draft/apply`, { revision: 2 })
  })

  it('未対応の定義は理由を表示し、導入操作を提供しない', async () => {
    get.mockResolvedValue({ ...definition, unavailable_reason: '未対応の設定定義です。' })
    render(<PluginSetupPanel pluginId="example.setup" onApplied={vi.fn()} />)
    expect(await screen.findByText('未対応の設定定義です。')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '次へ' })).not.toBeInTheDocument()
  })

  it('ホスト鍵の指紋照合を確認しない限り承認できない', async () => {
    const connection = { id: 'ssh1', name: 'ESXi 1', host: 'esxi.example.net', port: 22, username: 'reader', credential_id: 'key1', revision: 3, approved: false, fingerprint: null, candidate_fingerprint: 'SHA256:trusted' }
    get.mockImplementation(async path => {
      if (path.endsWith('/configuration')) return { ...definition, schema: { type: 'object', properties: { connection: { type: 'string', title: 'SSH', 'x-vea-widget': 'ssh-connection' } } }, draft: { config_values: { connection: 'ssh1' }, revision: 1, tests: {} } }
      if (path.endsWith('/credentials')) return [{ id: 'key1', name: '鍵', public_key: 'ssh-rsa PUBLIC' }]
      if (path.endsWith('/connections')) return [connection]
      return vcs
    })
    post.mockResolvedValue(connection)
    render(<PluginSetupPanel pluginId="example.setup" onApplied={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: '次へ' }))
    await screen.findByRole('button', { name: '接続先を追加・変更' })
    expect(screen.queryByRole('button', { name: 'このホスト鍵を承認' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '次へ' }))
    const approve = await screen.findByRole('button', { name: 'このホスト鍵を承認' })
    expect(approve).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox', { name: '管理者から入手した指紋と一致することを確認しました' }))
    expect(approve).toBeEnabled()
    fireEvent.click(approve)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/plugins/ssh/connections/ssh1/approve', { fingerprint: 'SHA256:trusted', revision: 3 }))
    expect(screen.queryByText('ssh-rsa PUBLIC')).not.toBeInTheDocument()
  })

  it('vCenter選択と配列編集を共通定義から表示し、接続先IDを維持する', async () => {
    const schema = { type: 'object', properties: { targets: { type: 'array', title: '対象', items: { type: 'object', properties: {
      id: { type: 'string', 'x-vea-generated-id': true },
      vc: { type: 'string', title: 'vCenter', 'x-vea-widget': 'vcenter' },
      mode: { type: 'string', title: 'モード', enum: ['one', 'two'], default: 'one' },
      enabled: { type: 'boolean', title: '使用する', default: false },
    } } } } }
    get.mockImplementation(async path => path.endsWith('/configuration') ? { ...definition, schema, draft: { config_values: { targets: [{ id: 'stable-source', vc: 'vc1', mode: 'one', enabled: false }] }, revision: 1, tests: {} } } : vcs)
    put.mockResolvedValue({ config_values: {}, revision: 2, tests: {} })
    render(<PluginSetupPanel pluginId="example.setup" onApplied={vi.fn()} />)
    await screen.findByLabelText('vCenter')
    expect(screen.getByRole('option', { name: '運用vCenter' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('モード'), { target: { value: 'two' } })
    fireEvent.click(screen.getByLabelText('使用する'))
    fireEvent.click(screen.getByText('その他の操作'))
    fireEvent.click(screen.getByRole('button', { name: '下書きを保存して中断' }))
    await waitFor(() => expect(put).toHaveBeenCalledWith(`${base}/draft`, { config_values: { targets: [{ id: 'stable-source', vc: 'vc1', mode: 'two', enabled: true }] }, revision: 1 }))
  })

  it('初期画面では現在の入力と次へだけを示し、保存・取り込みを折りたたむ', async () => {
    render(<PluginSetupPanel pluginId="example.setup" onApplied={vi.fn()} />)
    await screen.findByLabelText('センサー')
    expect(screen.getByRole('button', { name: '次へ' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: '接続テスト' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '現在の設定を下書きへ読み込む' })).not.toBeVisible()
    expect(screen.getByLabelText('設定の進捗').querySelector('[aria-current="step"]')).toHaveTextContent('設定項目')
    fireEvent.click(screen.getByText('その他の操作'))
    expect(screen.getByRole('button', { name: '現在の設定を下書きへ読み込む' })).toBeVisible()
  })

  it('検証失敗では次の手順に進まず入力内容を保持する', async () => {
    put.mockResolvedValue({ config_values: { sensor: 'board' }, revision: 2, tests: {} })
    post.mockRejectedValue(new Error('参照先を確認してください。'))
    render(<PluginSetupPanel pluginId="example.setup" onApplied={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: '次へ' }))
    await screen.findByRole('alert')
    expect(screen.getByLabelText('センサー')).toHaveValue('board')
    expect(screen.queryByRole('button', { name: '接続テスト' })).not.toBeInTheDocument()
  })
})


it('clears host candidates on vCenter changes and ignores a response from the previous selection', async () => {
  let finishOld!: (value: unknown) => void
  get.mockImplementation(path => path.includes('/vc1/')
    ? new Promise(resolve => { finishOld = resolve })
    : Promise.resolve([{ id: 'host2', name: 'New ESXi', host: 'new.example.net' }]))
  const schema = { type: 'string', 'x-vea-widget': 'esxi-host', 'x-vea-vcenter-field': 'vc' }
  const vcenters = [...vcs, { id: 'vc2', name: 'Second vCenter', host: 'vc2.example.net', is_enabled: true }]
  const onChange = vi.fn()
  const { rerender } = render(<SchemaFields schema={schema} value="" onChange={onChange} vcenters={vcenters} siblings={{ vc: 'vc1' }} />)
  fireEvent.click(screen.getByRole('button', { name: 'ESXi一覧を取得・再試行' }))
  expect(screen.getByRole('button', { name: 'ESXi一覧を取得・再試行' })).toBeDisabled()
  rerender(<SchemaFields schema={schema} value="" onChange={onChange} vcenters={vcenters} siblings={{ vc: 'vc2' }} />)
  expect(screen.getByRole('button', { name: 'ESXi一覧を取得・再試行' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'ESXi一覧を取得・再試行' }))
  await screen.findByRole('option', { name: 'New ESXi' })
  await act(async () => { finishOld([{ id: 'host1', name: 'Old ESXi', host: 'old.example.net' }]) })
  expect(screen.queryByRole('option', { name: 'Old ESXi' })).not.toBeInTheDocument()
  expect(screen.getByRole('option', { name: 'New ESXi' })).toBeInTheDocument()
  rerender(<SchemaFields schema={schema} value="" onChange={onChange} vcenters={vcenters} siblings={{ vc: 'vc1' }} />)
  expect(screen.queryByRole('option', { name: 'New ESXi' })).not.toBeInTheDocument()
})
