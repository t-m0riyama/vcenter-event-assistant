/**
 * @vitest-environment happy-dom
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { AUTH_DISABLED_ME, AuthContext } from './auth/authContext'
import type { Role } from './api/schemas'
import { AT, INCIDENT_DETAIL, INCIDENT_ID, INCIDENT_LIST, INCIDENT_TITLE, SNAPSHOT_ID } from './test/incidentFixtures'
import { emptyViewResponse, jsonResponse, VIEW_RESPONSE_EXAMPLE } from './test/timelineViewFixtures'

const listHash = '#/incidents'
const detailHash = `${listHash}/${INCIDENT_ID}`
const detailPath = `/api/incidents/${INCIDENT_ID}`
const proceduresPath = `${detailPath}/procedures`
const target = { id: '11111111-1111-4111-8111-111111111111', host_name: 'デモ ESXi' }
const procedure = {
  pattern_id: 'nic-link-flapping', title: 'NIC のリンクの不安定',
  steps: [{ text: '統計を確認します。', commands: [{ id: 'esxi.nic-stats', title: 'NIC の統計' }] }],
}
const diagnosticPath = `/api/diagnostics/incidents/${INCIDENT_ID}/runs`
const settingMeta = { revision: INCIDENT_ID, updated_by: 'デモ管理者', created_by: 'デモ管理者', updated_at: AT, created_at: AT }
const builtin = {
  id: 'esxi.nic-stats', product: 'esxi', title: 'NIC の統計', description: '',
  template: '画面では使わない雛形', param_definitions: [{ name: 'vmnic', type: 'vmnic' }],
}
const secondTarget = { ...target, id: '22222222-2222-4222-8222-222222222222', host_name: 'デモ ESXi 2' }
const vcenterTarget = { ...target, id: '33333333-3333-4333-8333-333333333333', host_name: 'デモ vCenter' }
const vcenterCommand = { ...builtin, id: 'vcenter.services', product: 'vcenter', title: 'vCenter のサービス', param_definitions: [] }
const custom = { ...builtin, ...settingMeta, id: INCIDENT_ID, title: '追加のデモコマンド' }
const savedRun = {
  id: 1, incident_id: INCIDENT_ID, command_kind: 'builtin', command_ref: builtin.id, command_title: builtin.title,
  command_line: 'プレビュー vmnic0', executed: true, params: { vmnic: 'vmnic0' }, target_id: target.id,
  product: 'esxi', host_name: target.host_name, ssh_host: 'ssh.demo.invalid', ssh_port: 2222, ssh_username: 'demo-user',
  status: 'failed', exit_status: 3, error_code: null, stdout_truncated: true, stderr_truncated: false,
  elapsed_ms: 140, started_at: AT, finished_at: AT, run_by: '運用者（op）',
} as const
const snapshotPath = `/api/incident-timeline/snapshots/manual/${SNAPSHOT_ID}`
const tab = (name: string) => within(document.querySelector('nav.tabs') as HTMLElement).getByRole('button', { name })
const respond404 = () => jsonResponse({ detail: 'missing' }, 404)

function appAs(role: Role, authEnabled: boolean, displayName: string) {
  const roles: Role[] = ['viewer', 'operator', 'admin']
  return (
    <AuthContext.Provider value={{
      me: { ...AUTH_DISABLED_ME, auth_enabled: authEnabled, display_name: displayName, username: 'op', role },
      hasRole: (minimum) => roles.indexOf(role) >= roles.indexOf(minimum),
      logout: vi.fn(),
      refresh: vi.fn(),
    }}>
      <App />
    </AuthContext.Provider>
  )
}

function renderApp(role: Role = 'admin', authEnabled = true, displayName = '運用者') {
  return render(appAs(role, authEnabled, displayName))
}

describe('App のインシデント画面', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  let snapshotMissing: boolean
  let snapshotUnreadable: boolean
  let updateCode: string
  let snapshotHasResult: boolean
  let latest = INCIDENT_DETAIL
  let updateStatus: number
  let detailStatus: number
  let diagnosticsEnabled: boolean
  let candidateTarget: typeof target | null
  let registeredTargets: typeof target[]
  let builtinCommands: (typeof builtin)[]
  let runRequest: (signal?: AbortSignal) => Promise<Response>
  let previewRequest: (body: { target_id: string; params: Record<string, string> }) => Promise<Response>

  beforeEach(() => {
    snapshotMissing = false
    snapshotUnreadable = false
    snapshotHasResult = true
    latest = INCIDENT_DETAIL
    updateStatus = 409
    detailStatus = 200
    diagnosticsEnabled = false
    candidateTarget = target
    registeredTargets = [target, secondTarget, vcenterTarget]
    builtinCommands = [builtin, vcenterCommand]
    runRequest = async () => jsonResponse(savedRun)
    previewRequest = async (body) => jsonResponse({
      command_line: `プレビュー ${body.params.vmnic ?? ''}`, host_name: '応答の対象名',
      ssh_host: 'ssh.demo.invalid', ssh_port: 2222, ssh_username: 'demo-user',
      fingerprint: `${body.target_id}:${body.params.vmnic ?? ''}`,
    })
    updateCode = 'incident_stale'
    window.history.replaceState(null, '', detailHash)
    fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), location.href)
      if (url.pathname === '/api/incidents' && init?.method === 'POST') return jsonResponse({
        incident: INCIDENT_DETAIL, link_results: { events: [], alerts: [], snapshots: [] },
      }, 201)
      if (url.pathname === '/api/incidents') return jsonResponse(INCIDENT_LIST)
      if (url.pathname === detailPath && init?.method === 'PATCH') {
        if (updateStatus === 200) return jsonResponse({ ...latest, ...JSON.parse(String(init.body)) })
        return jsonResponse({ detail: 'ユーザーが切り替わりました' }, updateStatus, { 'X-VEA-Error-Code': updateCode })
      }
      if (url.pathname === detailPath && init?.method !== 'DELETE') return jsonResponse(latest, detailStatus)
      if (url.pathname === proceduresPath) return jsonResponse([{ procedure, reasons: [{ kind: 'event', link_id: 1 }], target: candidateTarget }])
      if (url.pathname === '/api/diagnostics/commands') return jsonResponse({ builtin: builtinCommands, custom: [custom], parameter_types: ['vmnic'] })
      if (url.pathname === '/api/diagnostics/targets') return jsonResponse(registeredTargets.map((item) => ({
        ...settingMeta, ...item, vcenter_id: INCIDENT_ID, ssh_connection_id: INCIDENT_ID,
        product: item.id === vcenterTarget.id ? 'vcenter' : 'esxi',
        host_moid: item.id === vcenterTarget.id ? null : item.id,
      })))
      if (url.pathname === `${diagnosticPath}/preview`) return previewRequest(JSON.parse(String(init?.body)))
      if (url.pathname === diagnosticPath) return runRequest(init?.signal ?? undefined)
      if (url.pathname === `${detailPath}/diagnostic-runs/1`) return jsonResponse({ ...savedRun, stderr_truncated: true, stdout: '標準出力の内容', stderr: '標準エラーの内容' })
      if (url.pathname === '/api/event-patterns/procedures') return jsonResponse([procedure])
      if (url.pathname === '/api/config') return jsonResponse({
        event_retention_days: 7, metric_retention_days: 7, perf_sample_interval_seconds: 300,
        diagnostics_enabled: diagnosticsEnabled,
      })
      if (url.pathname === '/api/vcenters') return jsonResponse([])
      if (url.pathname === '/api/incident-timeline/view') return jsonResponse(emptyViewResponse())
      if (url.pathname === snapshotPath) {
        const { from_time: from, to_time: to, operator_note, created_at } = INCIDENT_DETAIL.snapshots[0]
        return snapshotMissing ? respond404() : jsonResponse({
          snapshot_id: SNAPSHOT_ID, from, to, operator_note, created_at, timestamp_utc: created_at, has_result: snapshotHasResult,
          view_request: { from, to }, build_request_payload: { from, to },
          result: !snapshotHasResult ? null : snapshotUnreadable ? { legacy: true } : VIEW_RESPONSE_EXAMPLE,
        })
      }
      return respond404()
    })
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => vi.unstubAllGlobals())

  it.each([
    ['viewer', true, false], ['operator', true, false], ['admin', false, false], ['admin', true, true],
  ] as const)('対応手順の実行の表示を制御する（%s、機能フラグ %s）', async (role, enabled, executable) => {
    diagnosticsEnabled = enabled
    renderApp(role)
    expect(await screen.findByText('NIC の統計')).toBeVisible()
    expect(screen.getByRole('heading', { name: '診断の結果' })).toBeVisible()
    if (executable) {
      expect(await screen.findByRole('button', { name: 'NIC の統計を実行' })).toBeEnabled()
    } else {
      expect(screen.queryByRole('button', { name: 'NIC の統計を実行' })).not.toBeInTheDocument()
      expect(fetchMock.mock.calls.some(([url]) => String(url).startsWith('/api/diagnostics/'))).toBe(false)
    }
  })

  const launchRun = async () => {
    const launch = await screen.findByRole('button', { name: 'NIC の統計を実行' })
    await waitFor(() => expect(launch).toBeEnabled())
    fireEvent.click(launch)
    return within(await screen.findByRole('dialog', { name: 'NIC の統計' }))
  }

  const openRun = async () => {
    diagnosticsEnabled = true
    renderApp()
    return launchRun()
  }

  const pauseNextDetail = () => {
    const original = fetchMock.getMockImplementation()!
    let resolve: ((response: Response) => void) | undefined
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === detailPath && !init?.method && !resolve) {
        return new Promise<Response>((done) => { resolve = done })
      }
      return original(input, init)
    })
    return {
      started: () => waitFor(() => expect(resolve).toBeDefined()),
      finish: (response: Response) => act(async () => { resolve?.(response) }),
    }
  }

  const previewRun = async (dialog: ReturnType<typeof within>) => {
    fireEvent.change(dialog.getByRole('textbox', { name: 'vmnic' }), { target: { value: 'vmnic0' } })
    fireEvent.click(dialog.getByRole('button', { name: 'プレビュー' }))
    expect(await dialog.findByText('プレビュー vmnic0')).toBeVisible()
    return dialog.getByRole('button', { name: '確認して実行' })
  }

  const requestsTo = (path: string) => fetchMock.mock.calls.filter(([url]) => String(url) === path)
  const recoveredRun = () => ({ ...savedRun, started_at: new Date(Date.now() + 1_000).toISOString() })
  const isRecovering = (dialog: ReturnType<typeof within>) => dialog.queryByText('最新の診断の結果を確認中…')
  const submittedBody = () => JSON.parse(String(requestsTo(diagnosticPath).at(-1)?.[1]?.body))

  it('プレビューの文字列と接続先をそのまま表示し、その指紋で実行する', async () => {
    const dialog = await openRun()
    expect(dialog.getByLabelText('対象')).toHaveValue(target.id)
    const execute = await previewRun(dialog)
    expect(dialog.getByText('応答の対象名')).toBeVisible()
    expect(dialog.getByText('ssh.demo.invalid（ポート 2222）')).toBeVisible()
    expect(dialog.getByText('demo-user')).toBeVisible()
    fireEvent.click(execute)
    await waitFor(() => expect(submittedBody()).toEqual({
      command: { builtin: builtin.id }, target_id: target.id, params: { vmnic: 'vmnic0' },
      fingerprint: `${target.id}:vmnic0`,
    }))
    expect(await dialog.findByText(/診断が失敗しました/)).toBeVisible()
    await waitFor(() => expect(requestsTo(detailPath)).toHaveLength(2))
  })

  it('対象や引数を変えると古いプレビューを使えず、再取得した指紋で実行する', async () => {
    const dialog = await openRun()
    const execute = await previewRun(dialog)
    fireEvent.change(dialog.getByLabelText('対象'), { target: { value: secondTarget.id } })
    expect(execute).toBeDisabled()
    expect(dialog.queryByText('プレビュー vmnic0')).not.toBeInTheDocument()
    expect(await dialog.findByText('プレビュー vmnic0')).toBeVisible()
    fireEvent.change(dialog.getByRole('textbox', { name: 'vmnic' }), { target: { value: 'vmnic2' } })
    expect(execute).toBeDisabled()
    expect(dialog.queryByText('プレビュー vmnic0')).not.toBeInTheDocument()
    expect(requestsTo(diagnosticPath)).toHaveLength(0)
    expect(await dialog.findByText('プレビュー vmnic2')).toBeVisible()
    expect(requestsTo(`${diagnosticPath}/preview`)).toHaveLength(3)
    fireEvent.click(execute)
    await waitFor(() => expect(submittedBody().fingerprint).toBe(`${secondTarget.id}:vmnic2`))
  })

  it('先に要求したプレビューが遅れて届いても、新しいプレビューを維持する', async () => {
    const dialog = await openRun()
    const field = dialog.getByRole('textbox', { name: 'vmnic' })
    const respond = previewRequest
    let respondOld!: (response: Response) => void
    previewRequest = (body) => body.params.vmnic === 'vmnic0'
      ? new Promise((resolve) => { respondOld = resolve })
      : respond(body)
    fireEvent.change(field, { target: { value: 'vmnic0' } })
    fireEvent.click(dialog.getByRole('button', { name: 'プレビュー' }))
    await waitFor(() => expect(respondOld).toBeTypeOf('function'))
    fireEvent.change(field, { target: { value: 'vmnic1' } })
    expect(await dialog.findByText('プレビュー vmnic1')).toBeVisible()
    await act(async () => respondOld(await respond({ target_id: target.id, params: { vmnic: 'vmnic0' } })))
    expect(dialog.getByText('プレビュー vmnic1')).toBeVisible()
    expect(dialog.queryByText('プレビュー vmnic0')).not.toBeInTheDocument()
    expect(dialog.getByRole('button', { name: '確認して実行' })).toBeEnabled()
  })

  it('変更の 409 では実行を繰り返さず、新しいプレビューを出す', async () => {
    const dialog = await openRun()
    const execute = await previewRun(dialog)
    runRequest = async () => jsonResponse({}, 409, { 'X-VEA-Error-Code': 'diagnostic_changed' })
    previewRequest = async () => jsonResponse({
      command_line: 'サーバーの新しいコマンド', host_name: '新しい対象',
      ssh_host: 'new.demo.invalid', ssh_port: 2222, ssh_username: 'new-demo-user', fingerprint: 'new-fingerprint',
    })
    fireEvent.click(execute)
    expect(await dialog.findByText('サーバーの新しいコマンド')).toBeVisible()
    expect(dialog.getByText('new.demo.invalid（ポート 2222）')).toBeVisible()
    expect(requestsTo(diagnosticPath)).toHaveLength(1)
    expect(requestsTo(`${diagnosticPath}/preview`)).toHaveLength(2)
    runRequest = async () => jsonResponse(savedRun)
    fireEvent.click(execute)
    await waitFor(() => expect(submittedBody().fingerprint).toBe('new-fingerprint'))
  })

  it.each([
    ['diagnostic_busy', /実行枠に空きがありません/],
    ['incident_diagnostic_limit', /100 件まで/],
  ] as const)('409 の区分 %s に応じて案内する', async (code, message) => {
    const dialog = await openRun()
    const execute = await previewRun(dialog)
    runRequest = async () => jsonResponse({ detail: '共通の応答' }, 409, { 'X-VEA-Error-Code': code })
    fireEvent.click(execute)
    expect(await dialog.findByRole('alert')).toHaveTextContent(message)
    expect(requestsTo(`${diagnosticPath}/preview`)).toHaveLength(1)
  })

  it('422 の引数の区分を該当する欄に出す', async () => {
    const dialog = await openRun()
    previewRequest = async () => jsonResponse({
      detail: [{ parameter: 'vmnic', reason: 'invalid_value' }],
    }, 422, { 'X-VEA-Error-Code': 'diagnostic_params_invalid' })
    const field = dialog.getByRole('textbox', { name: 'vmnic' })
    fireEvent.change(field, { target: { value: '形式違い' } })
    fireEvent.click(dialog.getByRole('button', { name: 'プレビュー' }))
    expect(await dialog.findByText('値の形式を確認してください。')).toBeVisible()
    expect(field).toHaveAttribute('aria-invalid', 'true')
    expect(field).toHaveAccessibleDescription('値の形式を確認してください。')
    expect(dialog.getByRole('button', { name: '確認して実行' })).toBeDisabled()
  })

  it('実行中は連続して送信されても二重実行しない', async () => {
    const dialog = await openRun()
    const execute = await previewRun(dialog)
    let finish!: (response: Response) => void
    runRequest = () => new Promise((resolve) => { finish = resolve })
    const form = execute.closest('form')!
    act(() => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    })
    expect(execute).toBeDisabled()
    expect(dialog.getByText(/実行中… 結果の保存まで最大でおよそ 55 秒/)).toBeVisible()
    expect(dialog.getByRole('button', { name: '閉じる' })).toBeDisabled()
    expect(requestsTo(diagnosticPath)).toHaveLength(1)
    await act(async () => finish(jsonResponse(savedRun)))
  })

  const moveByHash = async (hash: string) => {
    await act(async () => {
      const oldURL = window.location.href
      window.history.replaceState(null, '', hash)
      window.dispatchEvent(new HashChangeEvent('hashchange', { oldURL, newURL: window.location.href }))
    })
  }

  it('実行中に履歴で別のタブや一覧に移っても、同じ操作の結果まで保持する', async () => {
    const dialog = await openRun()
    let finish!: (response: Response) => void
    runRequest = () => new Promise((resolve) => { finish = resolve })
    fireEvent.click(await previewRun(dialog))
    await moveByHash('#/summary')
    expect(screen.queryByRole('dialog', { name: 'NIC の統計' })).not.toBeInTheDocument()
    await moveByHash(listHash)
    await moveByHash(detailHash)
    const returned = within(await screen.findByRole('dialog', { name: 'NIC の統計' }))
    expect(returned.getByText(/実行中/)).toBeVisible()
    const retry = returned.getByRole('button', { name: '確認して実行' })
    expect(retry).toBeDisabled()
    fireEvent.click(retry)
    expect(requestsTo(diagnosticPath)).toHaveLength(1)
    await moveByHash('#/summary')
    latest = { ...INCIDENT_DETAIL, diagnostic_runs: [savedRun] }
    await act(async () => finish(jsonResponse(savedRun)))
    await moveByHash(detailHash)
    expect(await screen.findByText(/診断が失敗しました/)).toBeVisible()
    expect(screen.queryByRole('button', { name: '確認して実行' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '閉じる' }))
    expect(await screen.findByText('失敗')).toBeVisible()
    expect(requestsTo(diagnosticPath)).toHaveLength(1)
  })

  it('実行中の Esc を抑え、取り消せない閉じ方でも同じダイアログと結果を表示する', async () => {
    const dialog = await openRun()
    let finish!: (response: Response) => void
    runRequest = () => new Promise((resolve) => { finish = resolve })
    fireEvent.click(await previewRun(dialog))
    const element = screen.getByRole<HTMLDialogElement>('dialog', { name: 'NIC の統計' })
    const cancel = new Event('cancel', { cancelable: true })
    fireEvent(element, cancel)
    expect(cancel.defaultPrevented).toBe(true)
    fireEvent(element, new Event('cancel'))
    element.close()
    fireEvent(element, new Event('close'))
    expect(element.open).toBe(true)
    expect(dialog.getByText(/実行中/)).toBeVisible()
    expect(dialog.getByRole('button', { name: '確認して実行' })).toBeDisabled()
    await act(async () => finish(jsonResponse(savedRun)))
    expect(await dialog.findByText(/診断が失敗しました/)).toBeVisible()
    expect(requestsTo(diagnosticPath)).toHaveLength(1)
  })

  it('実行の応答が切れ、最初の読み直しに結果がなくても保存後に表示する', async () => {
    const dialog = await openRun()
    runRequest = async () => { throw new TypeError('接続が切断されました') }
    fireEvent.click(await previewRun(dialog))
    expect(await dialog.findByText(/実行の応答を受け取れませんでした/)).toBeVisible()
    await waitFor(() => expect(requestsTo(detailPath)).toHaveLength(2))
    latest = {
      ...INCIDENT_DETAIL, diagnostic_runs: [recoveredRun()],
      entries: [...INCIDENT_DETAIL.entries, {
        id: 3, incident_id: INCIDENT_ID, kind: 'diagnostic', body: '診断を保存しました。',
        author: 'デモ管理者', created_at: AT, deleted_at: null, deleted_by: null,
      }],
    }
    await waitFor(() => expect(isRecovering(dialog)).not.toBeInTheDocument(), { timeout: 7000 })
    fireEvent.click(dialog.getByRole('button', { name: '閉じる' }))
    expect(screen.getByText('診断を保存しました。')).toBeVisible()
    expect(screen.getByText('失敗')).toBeVisible()
  }, 12_000)

  it.each([502, 504])('区分のない %s では自分の同じ接続先の結果が保存されるまで読み直す', async (status) => {
    const dialog = await openRun()
    const execute = await previewRun(dialog)
    runRequest = async () => {
      latest = { ...INCIDENT_DETAIL, diagnostic_runs: [{ ...recoveredRun(), ssh_host: 'other.demo.invalid' }] }
      return new Response('プロキシが接続を終了しました', { status })
    }
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] })
    try {
      await act(async () => { fireEvent.click(execute) })
      expect(dialog.getByRole('alert')).toHaveTextContent('実行の応答を受け取れませんでした')
      expect(requestsTo(detailPath)).toHaveLength(2)
      expect(isRecovering(dialog)).toBeVisible()

      latest = { ...INCIDENT_DETAIL, diagnostic_runs: [{ ...recoveredRun(), id: 2, run_by: '別の管理者' }] }
      await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
      expect(requestsTo(detailPath)).toHaveLength(3)
      expect(isRecovering(dialog)).toBeVisible()

      latest = { ...INCIDENT_DETAIL, diagnostic_runs: [{ ...recoveredRun(), id: 3 }] }
      await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
      expect(requestsTo(detailPath)).toHaveLength(4)
      expect(isRecovering(dialog)).not.toBeInTheDocument()
      expect(dialog.getByText('保存された結果が見つかりました。')).toBeVisible()
      expect(dialog.queryByText(/実行の応答を受け取れませんでした/)).not.toBeInTheDocument()
      expect(requestsTo(diagnosticPath)).toHaveLength(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it('応答が遅れて切れてもその時点から読み直しを続け、最後は手動でも確認できる', async () => {
    const dialog = await openRun()
    const execute = await previewRun(dialog)
    let finish!: (response: Response) => void
    runRequest = () => new Promise((resolve) => { finish = resolve })
    const close = dialog.getByRole('button', { name: '閉じる' })
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] })
    try {
      await act(async () => { fireEvent.click(execute) })
      await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })
      expect(requestsTo(detailPath)).toHaveLength(1)
      await act(async () => { finish(new Response('接続が途切れました', { status: 504 })) })
      await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })
      expect(isRecovering(dialog)).toBeVisible()
      await act(async () => { await vi.advanceTimersByTimeAsync(5_000) })
      expect(dialog.queryByRole('button', { name: 'プレビュー' })).not.toBeInTheDocument()
      expect(dialog.queryByRole('button', { name: '確認して実行' })).not.toBeInTheDocument()
      const refresh = dialog.getByRole('button', { name: '結果を読み直す' })
      expect(refresh).toBeEnabled()
      latest = { ...INCIDENT_DETAIL, diagnostic_runs: [recoveredRun()] }
      await act(async () => { fireEvent.click(refresh) })
      expect(requestsTo(diagnosticPath)).toHaveLength(1)
      fireEvent.click(close)
      expect(screen.getByText('失敗')).toBeVisible()
    } finally {
      vi.useRealTimers()
    }
  })

  it('同じ利用者の同じコマンドの既存の結果で回復を終えない', async () => {
    latest = { ...INCIDENT_DETAIL, diagnostic_runs: [recoveredRun()] }
    const dialog = await openRun()
    runRequest = async () => new Response(null, { status: 502 })
    const execute = await previewRun(dialog)
    vi.useFakeTimers()
    try {
      await act(async () => { fireEvent.click(execute) })
      expect(isRecovering(dialog)).toBeVisible()
      expect(dialog.queryByText('保存された結果が見つかりました。')).not.toBeInTheDocument()
      latest = { ...latest, diagnostic_runs: [...latest.diagnostic_runs, { ...recoveredRun(), id: 2 }] }
      await act(async () => { await vi.advanceTimersByTimeAsync(5_000) })
      expect(dialog.getByText('保存された結果が見つかりました。')).toBeVisible()
    } finally {
      vi.useRealTimers()
    }
  })

  it.each([
    ['target_id', secondTarget.id],
    ['command_kind', 'custom'],
    ['command_ref', 'esxi.hostname'],
    ['command_line', '別のコマンド文字列'],
    ['ssh_port', 22],
    ['ssh_username', 'another-user'],
    ['started_at', AT],
  ] as const)('回復の照合で %s だけ異なる結果を使わない', async (field, value) => {
    const dialog = await openRun()
    const execute = await previewRun(dialog)
    runRequest = async () => {
      latest = { ...INCIDENT_DETAIL, diagnostic_runs: [{ ...recoveredRun(), [field]: value }] }
      return new Response(null, { status: 504 })
    }
    vi.useFakeTimers()
    try {
      await act(async () => { fireEvent.click(execute) })
      expect(isRecovering(dialog)).toBeVisible()
      expect(dialog.queryByText('保存された結果が見つかりました。')).not.toBeInTheDocument()
      latest = { ...INCIDENT_DETAIL, diagnostic_runs: [{ ...recoveredRun(), id: 2 }] }
      await act(async () => { await vi.advanceTimersByTimeAsync(5_000) })
      expect(dialog.getByText('保存された結果が見つかりました。')).toBeVisible()
    } finally {
      vi.useRealTimers()
    }
  })

  it('サーバーの時計がブラウザより遅れていても、保存された自分の結果を見つける', async () => {
    const dialog = await openRun()
    const execute = await previewRun(dialog)
    runRequest = async () => {
      latest = { ...INCIDENT_DETAIL, diagnostic_runs: [{ ...savedRun, id: 9, started_at: new Date(Date.now() - 2_000).toISOString() }] }
      return new Response(null, { status: 504 })
    }
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] })
    try {
      await act(async () => { fireEvent.click(execute) })
      await act(async () => { await vi.advanceTimersByTimeAsync(0) })
      expect(dialog.getByText('保存された結果が見つかりました。')).toBeVisible()
    } finally {
      vi.useRealTimers()
    }
  })

  it('AbortSignal.any と AbortSignal.timeout が無いブラウザでも実行を送る', async () => {
    const dialog = await openRun()
    const execute = await previewRun(dialog)
    const any = Object.getOwnPropertyDescriptor(AbortSignal, 'any')
    const timeout = Object.getOwnPropertyDescriptor(AbortSignal, 'timeout')
    Object.defineProperty(AbortSignal, 'any', { value: undefined, configurable: true })
    Object.defineProperty(AbortSignal, 'timeout', { value: undefined, configurable: true })
    try {
      await act(async () => { fireEvent.click(execute) })
      await waitFor(() => expect(requestsTo(diagnosticPath)).toHaveLength(1))
      await waitFor(() => expect(requestsTo(detailPath).length).toBeGreaterThan(1))
      expect(dialog.queryByRole('alert')).not.toBeInTheDocument()
    } finally {
      // 親から受け継いだ関数のときは、上書きした自身のプロパティを消して元に戻す。
      if (any) Object.defineProperty(AbortSignal, 'any', any)
      else Reflect.deleteProperty(AbortSignal, 'any')
      if (timeout) Object.defineProperty(AbortSignal, 'timeout', timeout)
      else Reflect.deleteProperty(AbortSignal, 'timeout')
      expect(typeof AbortSignal.any).toBe('function')
      expect(typeof AbortSignal.timeout).toBe('function')
    }
  })

  it('確定した失敗の読み直し中に隠したダイアログが閉じても、フォーカスを動かさない', async () => {
    const dialog = await openRun()
    const execute = await previewRun(dialog)
    runRequest = async () => jsonResponse({}, 409, { 'X-VEA-Error-Code': 'diagnostic_busy' })
    const request = pauseNextDetail()
    fireEvent.click(execute)
    await request.started()
    fireEvent.click(dialog.getByRole('button', { name: '閉じる' }))
    const other = screen.getByRole('button', { name: '編集' })
    other.focus()
    await act(async () => { await request.finish(jsonResponse(INCIDENT_DETAIL)) })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(document.activeElement).toBe(other)
  })

  it('実行要求は 70 秒で切り、結果の確認を始める', async () => {
    const dialog = await openRun()
    const execute = await previewRun(dialog)
    runRequest = (signal) => new Promise((_resolve, reject) => {
      signal?.addEventListener('abort', () => reject(signal.reason), { once: true })
    })
    vi.useFakeTimers()
    const timeout = vi.spyOn(AbortSignal, 'timeout').mockImplementation((ms) => {
      const controller = new AbortController()
      setTimeout(() => controller.abort(new DOMException('時間切れ', 'TimeoutError')), ms)
      return controller.signal
    })
    try {
      await act(async () => { fireEvent.click(execute) })
      await act(async () => { await vi.advanceTimersByTimeAsync(69_999) })
      expect(dialog.getByText(/実行中…/)).toBeVisible()
      expect(requestsTo(detailPath)).toHaveLength(1)
      await act(async () => { await vi.advanceTimersByTimeAsync(1) })
      expect(timeout).toHaveBeenCalledWith(70_000)
      expect(isRecovering(dialog)).toBeVisible()
      expect(requestsTo(detailPath)).toHaveLength(2)
    } finally {
      timeout.mockRestore()
      vi.useRealTimers()
    }
  })

  it('オフラインで回復中でも閉じて同じ確認状況に戻れる', async () => {
    const dialog = await openRun()
    const execute = await previewRun(dialog)
    runRequest = async () => { throw new TypeError('接続が切断されました') }
    vi.useFakeTimers()
    try {
      await act(async () => { fireEvent.click(execute) })
      expect(isRecovering(dialog)).toBeVisible()
      fireEvent.click(dialog.getByRole('button', { name: '閉じる' }))
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: '診断の結果確認を開く' }))
      const waiting = within(screen.getByRole('dialog', { name: 'NIC の統計' }))
      expect(isRecovering(waiting)).toBeVisible()
      expect(waiting.queryByRole('button', { name: 'プレビュー' })).not.toBeInTheDocument()
      fireEvent.click(waiting.getByRole('button', { name: '閉じる' }))
      latest = { ...INCIDENT_DETAIL, diagnostic_runs: [{ ...recoveredRun(), id: 2 }] }
      await act(async () => { await vi.advanceTimersByTimeAsync(5_000) })
      expect(screen.getByText('失敗')).toBeVisible()
      fireEvent.click(screen.getByRole('button', { name: '診断の結果確認を開く' }))
      const reopened = within(screen.getByRole('dialog', { name: 'NIC の統計' }))
      expect(reopened.getByText('保存された結果が見つかりました。')).toBeVisible()
      expect(reopened.queryByRole('button', { name: 'プレビュー' })).not.toBeInTheDocument()
      expect(requestsTo(diagnosticPath)).toHaveLength(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it.each([
    [409, 'diagnostic_busy', '診断の実行枠に空きがありません。'],
    [429, null, '短い間に実行が多すぎます。しばらく待ってから実行してください。'],
  ])('確定した %s は履歴で離れるとダイアログを閉じる', async (status, code, message) => {
    const dialog = await openRun()
    runRequest = async () => jsonResponse({}, status, code ? { 'X-VEA-Error-Code': code } : {})
    fireEvent.click(await previewRun(dialog))
    expect(await dialog.findByRole('alert')).toHaveTextContent(message)
    await waitFor(() => expect(dialog.getByRole('button', { name: 'プレビュー' })).toBeEnabled())
    await moveByHash('#/summary')
    await moveByHash(detailHash)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(requestsTo(diagnosticPath)).toHaveLength(1)
  })

  it('履歴で再描画された実行ボタンにフォーカスを戻す', async () => {
    const dialog = await openRun()
    const trigger = screen.getByRole('button', { name: 'NIC の統計を実行' })
    let finish!: (value: Response) => void
    runRequest = () => new Promise((resolve) => { finish = resolve })
    fireEvent.click(await previewRun(dialog))
    await moveByHash('#/summary')
    await act(async () => { finish(jsonResponse(savedRun)) })
    await moveByHash(detailHash)
    const rebuiltTrigger = await screen.findByRole('button', { name: 'NIC の統計を実行' })
    expect(rebuiltTrigger).not.toBe(trigger)
    fireEvent.click(screen.getByRole('button', { name: '閉じる' }))
    expect(rebuiltTrigger).toHaveFocus()
  })

  it('成功した実行は詳細を読み直したあとも同じダイアログから再実行できない', async () => {
    const dialog = await openRun()
    runRequest = async () => jsonResponse({ ...savedRun, status: 'succeeded', exit_status: 0 })
    fireEvent.click(await previewRun(dialog))
    expect(await dialog.findByText('診断の結果に保存しました。')).toBeVisible()
    await waitFor(() => expect(dialog.getByRole('button', { name: '閉じる' })).toBeEnabled())
    expect(dialog.queryByRole('button', { name: '確認して実行' })).not.toBeInTheDocument()
    expect(dialog.queryByRole('button', { name: 'プレビュー' })).not.toBeInTheDocument()
    expect(requestsTo(diagnosticPath)).toHaveLength(1)
  })

  it.each([
    [500, 'diagnostic_internal_error', '診断の処理中にエラーが発生しました。'],
    [503, 'diagnostic_save_failed', '診断の結果を保存できませんでした。'],
    [409, 'incident_diagnostic_limit', '100 件まで'],
    [404, 'incident_not_found', 'インシデントが見つかりません。'],
  ])('実行後の %s %s は結果を確認するよう案内し、古いプレビューを消す', async (status, code, message) => {
    const dialog = await openRun()
    runRequest = async () => jsonResponse({}, status, { 'X-VEA-Error-Code': code })
    const execute = await previewRun(dialog)
    fireEvent.click(execute)
    expect(await dialog.findByRole('alert')).toHaveTextContent(message)
    expect(dialog.getByText('結果を確かめてから、必要ならプレビューを取り直して実行してください。')).toBeVisible()
    await waitFor(() => expect(dialog.getByRole('button', { name: 'プレビュー' })).toBeEnabled())
    expect(dialog.queryByText('プレビュー vmnic0')).not.toBeInTheDocument()
    expect(execute).toBeDisabled()
    fireEvent.click(execute)
    expect(requestsTo(diagnosticPath)).toHaveLength(1)
    expect(requestsTo(detailPath)).toHaveLength(2)
  })

  it.each([
    [404, 'diagnostic_target_not_found', '診断の対象が見つかりません。'],
    [404, 'diagnostic_command_not_found', '診断のコマンドが見つかりません。'],
    [404, 'diagnostic_connection_not_found', '診断用の SSH 接続先が見つかりません。'],
    [404, 'diagnostic_credential_not_found', '診断用の SSH 鍵が見つかりません。'],
    [409, 'diagnostic_host_key_unapproved', '接続先のホスト鍵を承認してください。'],
  ])('%s %s の理由を表示し、確認済みのプレビューを取り消す', async (status, code, message) => {
    const dialog = await openRun()
    runRequest = async () => jsonResponse({}, status, { 'X-VEA-Error-Code': code })
    const execute = await previewRun(dialog)
    fireEvent.click(execute)
    expect(await dialog.findByRole('alert')).toHaveTextContent(message)
    await waitFor(() => expect(dialog.getByRole('button', { name: 'プレビュー' })).toBeEnabled())
    expect(dialog.queryByText('プレビュー vmnic0')).not.toBeInTheDocument()
    expect(execute).toBeDisabled()
  })

  it('実行時の 422 もプレビューを取り消し、欄の誤りを名前と分けて表示する', async () => {
    const dialog = await openRun()
    const execute = await previewRun(dialog)
    runRequest = async () => jsonResponse({ detail: [{ parameter: 'vmnic', reason: 'invalid_value' }] }, 422, {
      'X-VEA-Error-Code': 'diagnostic_params_invalid',
    })
    fireEvent.click(execute)
    expect(await dialog.findByText('値の形式を確認してください。')).toBeVisible()
    const field = dialog.getByRole('textbox', { name: 'vmnic' })
    expect(field).toHaveAccessibleDescription('値の形式を確認してください。')
    await waitFor(() => expect(dialog.getByRole('button', { name: 'プレビュー' })).toBeEnabled())
    expect(dialog.queryByText('プレビュー vmnic0')).not.toBeInTheDocument()
    expect(execute).toBeDisabled()
  })

  it('実行後の読み直しで 404 が返ったら一覧に戻る', async () => {
    const dialog = await openRun()
    const execute = await previewRun(dialog)
    runRequest = async () => {
      detailStatus = 404
      return jsonResponse({}, 404, { 'X-VEA-Error-Code': 'incident_not_found' })
    }
    fireEvent.click(execute)
    expect(await screen.findByText('インシデントが見つかりません')).toBeVisible()
    expect(window.location.hash).toBe(listHash)
    expect(screen.queryByText('詳細を読み直せませんでした。')).not.toBeInTheDocument()
  })

  it('詳細の読み直しに失敗した場合はエラーを表示し、結果だけを手動で読み直せる', async () => {
    const dialog = await openRun()
    const execute = await previewRun(dialog)
    runRequest = async () => {
      detailStatus = 503
      return jsonResponse(savedRun)
    }
    fireEvent.click(execute)
    expect(await dialog.findByText('詳細を読み直せませんでした。')).toBeVisible()
    detailStatus = 200
    latest = { ...INCIDENT_DETAIL, diagnostic_runs: [savedRun] }
    const refresh = dialog.getByRole('button', { name: '結果を読み直す' })
    await waitFor(() => expect(refresh).toBeEnabled())
    fireEvent.click(refresh)
    await waitFor(() => expect(refresh).not.toBeInTheDocument())
    fireEvent.click(dialog.getByRole('button', { name: '閉じる' }))
    expect(await screen.findByText('失敗')).toBeVisible()
    expect(requestsTo(diagnosticPath)).toHaveLength(1)
  })

  it('インシデントが消えたあと同じ URL を開くと詳細を新しく取得する', async () => {
    const dialog = await openRun()
    const execute = await previewRun(dialog)
    runRequest = async () => {
      detailStatus = 404
      return jsonResponse(savedRun)
    }
    fireEvent.click(execute)
    expect(await screen.findByText('インシデントが見つかりません')).toBeVisible()

    detailStatus = 200
    const request = pauseNextDetail()
    await moveByHash(detailHash)
    await request.started()
    expect(window.location.hash).toBe(detailHash)
    expect(screen.queryByRole('heading', { name: INCIDENT_TITLE })).not.toBeInTheDocument()
    await request.finish(jsonResponse({ ...INCIDENT_DETAIL, title: '再取得したインシデント' }))
    expect(await screen.findByRole('heading', { name: '再取得したインシデント' })).toBeVisible()
  })

  it('ダイアログを閉じて一覧に戻ったあと詳細を新しく取得する', async () => {
    const dialog = await openRun()
    fireEvent.click(dialog.getByRole('button', { name: '閉じる' }))
    await moveByHash(listHash)
    const request = pauseNextDetail()
    await moveByHash(detailHash)
    await request.started()
    expect(screen.queryByRole('heading', { name: INCIDENT_TITLE })).not.toBeInTheDocument()
    await request.finish(jsonResponse({ ...INCIDENT_DETAIL, title: '閉じた後に取得した詳細' }))
    expect(await screen.findByRole('heading', { name: '閉じた後に取得した詳細' })).toBeVisible()
  })

  it('実行中に権限を失っても読み直しを終え、権限が戻ったとき旧ダイアログを再表示しない', async () => {
    diagnosticsEnabled = true
    const app = renderApp()
    const dialog = await launchRun()
    let finish!: (response: Response) => void
    runRequest = () => new Promise((resolve) => { finish = resolve })
    fireEvent.click(await previewRun(dialog))
    app.rerender(appAs('operator', true, '運用者'))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    latest = { ...INCIDENT_DETAIL, diagnostic_runs: [savedRun] }
    await act(async () => { finish(jsonResponse(savedRun)) })
    expect(await screen.findByText('失敗')).toBeVisible()
    app.rerender(appAs('admin', true, '運用者'))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '診断の結果確認を開く' })).not.toBeInTheDocument()
    const fresh = await launchRun()
    expect(fresh.getByRole('button', { name: 'プレビュー' })).toBeEnabled()
  })

  it.each(['実行', '手動の読み直し'] as const)('%s の開始前に要求した古い詳細を処理中に受け取っても反映しない', async (action) => {
    const initial = await openRun()
    if (action === '手動の読み直し') {
      runRequest = async () => {
        detailStatus = 503
        return jsonResponse(savedRun)
      }
      fireEvent.click(await previewRun(initial))
      await waitFor(() => expect(initial.getByRole('button', { name: '結果を読み直す' })).toBeEnabled())
      detailStatus = 200
    }

    await moveByHash('#/summary')
    const stale = pauseNextDetail()
    await moveByHash(detailHash)
    await stale.started()
    if (action === '実行') {
      const dialog = await launchRun()
      let finish!: (response: Response) => void
      runRequest = () => new Promise((done) => { finish = done })
      fireEvent.click(await previewRun(dialog))
      await stale.finish(jsonResponse({ ...INCIDENT_DETAIL, title: '古い詳細' }))
      expect(screen.queryByRole('heading', { name: '古い詳細' })).not.toBeInTheDocument()
      latest = { ...INCIDENT_DETAIL, diagnostic_runs: [savedRun] }
      await act(async () => { finish(jsonResponse(savedRun)) })
    } else {
      const reread = pauseNextDetail()
      fireEvent.click(screen.getByRole('button', { name: '結果を読み直す' }))
      await reread.started()
      await stale.finish(jsonResponse({ ...INCIDENT_DETAIL, title: '古い詳細' }))
      expect(screen.queryByRole('heading', { name: '古い詳細' })).not.toBeInTheDocument()
      await reread.finish(jsonResponse({ ...INCIDENT_DETAIL, diagnostic_runs: [savedRun] }))
    }
    expect(screen.getByText('失敗')).toBeVisible()
  })

  it.each([
    ['実行', 200],
    ['手動の読み直し', 200],
    ['実行', 404],
  ] as const)('%s の途中に要求した古い %s は結果を取得したあとに反映しない', async (action, status) => {
    const dialog = await openRun()
    let finishAction!: () => Promise<void>
    if (action === '実行') {
      let finish!: (response: Response) => void
      runRequest = () => new Promise((resolve) => { finish = resolve })
      fireEvent.click(await previewRun(dialog))
      finishAction = () => act(async () => { finish(jsonResponse(savedRun)) })
    } else {
      runRequest = async () => {
        detailStatus = 503
        return jsonResponse(savedRun)
      }
      fireEvent.click(await previewRun(dialog))
      const button = await dialog.findByRole('button', { name: '結果を読み直す' })
      await waitFor(() => expect(button).toBeEnabled())
      detailStatus = 200
      const reread = pauseNextDetail()
      fireEvent.click(button)
      await reread.started()
      finishAction = () => reread.finish(jsonResponse(latest))
    }

    await moveByHash('#/summary')
    const stale = pauseNextDetail()
    await moveByHash(detailHash)
    await stale.started()
    latest = { ...INCIDENT_DETAIL, diagnostic_runs: [savedRun] }
    await finishAction()
    expect(screen.getByText('失敗')).toBeVisible()
    await stale.finish(jsonResponse(INCIDENT_DETAIL, status))
    expect(screen.getByText('失敗')).toBeVisible()
    expect(window.location.hash).toBe(detailHash)
  })

  it('件名を編集中でも下書きと読み直した診断結果を表示する', async () => {
    diagnosticsEnabled = true
    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: '編集' }))
    const title = screen.getByRole('textbox', { name: /件名/ })
    fireEvent.change(title, { target: { value: '保存前の診断メモ' } })
    const launch = await screen.findByRole('button', { name: 'NIC の統計を実行' })
    await waitFor(() => expect(launch).toBeEnabled())
    fireEvent.click(launch)
    const dialog = within(await screen.findByRole('dialog', { name: 'NIC の統計' }))
    runRequest = async () => {
      latest = { ...INCIDENT_DETAIL, title: 'サーバー上の件名', diagnostic_runs: [savedRun] }
      return jsonResponse(savedRun)
    }
    fireEvent.click(await previewRun(dialog))
    const close = dialog.getByRole('button', { name: '閉じる' })
    await waitFor(() => expect(close).toBeEnabled())
    fireEvent.click(close)
    expect(title).toHaveValue('保存前の診断メモ')
    expect(await screen.findByText('失敗')).toBeVisible()
  })

  it('別製品の候補の対象は先に選ばず、選択肢にも表示しない', async () => {
    candidateTarget = vcenterTarget
    const dialog = await openRun()
    expect(dialog.getByLabelText('対象')).toHaveValue('')
    expect(dialog.queryByRole('option', { name: vcenterTarget.host_name })).not.toBeInTheDocument()
    expect(dialog.getByRole('option', { name: target.host_name })).toBeVisible()
  })

  it('ダイアログを開くと最新の引数の定義と対象を表示し、閉じると実行ボタンにフォーカスを戻す', async () => {
    diagnosticsEnabled = true
    renderApp()
    const launch = await screen.findByRole('button', { name: 'NIC の統計を実行' })
    await waitFor(() => expect(launch).toBeEnabled())
    builtinCommands = [{ ...builtin, param_definitions: [{ name: 'nic', type: 'vmnic' }] }]
    registeredTargets = [{ ...target, host_name: '更新後の対象' }]
    screen.getByRole('button', { name: '一覧に戻る' }).focus()
    fireEvent.click(launch)
    const dialog = within(await screen.findByRole('dialog', { name: 'NIC の統計' }))
    expect(dialog.getByRole('textbox', { name: 'nic（vmnic）' })).toBeVisible()
    expect(dialog.getByRole('option', { name: '更新後の対象' })).toBeVisible()
    expect(requestsTo('/api/diagnostics/commands')).toHaveLength(2)
    expect(requestsTo('/api/diagnostics/targets')).toHaveLength(2)
    fireEvent.click(dialog.getByRole('button', { name: '閉じる' }))
    expect(launch).toHaveFocus()
  })

  it('診断のエラー区分を開くと原因を日本語で表示する', async () => {
    latest = { ...INCIDENT_DETAIL, diagnostic_runs: [{ ...savedRun, status: 'error', error_code: 'host_key_mismatch', exit_status: null }] }
    renderApp('viewer')
    const badge = await screen.findByText('エラー')
    expect(badge).toHaveClass('badge--error')
    fireEvent.click(badge.closest('summary')!)
    expect(screen.getByText('ホスト鍵が承認済みの鍵と一致しません。')).toBeVisible()
  })

  it('viewer も結果を開ける。出力の取得は開いたあとに行い、切り詰めを表示する', async () => {
    latest = { ...INCIDENT_DETAIL, diagnostic_runs: [savedRun] }
    renderApp('viewer')
    const summary = (await screen.findByText('失敗')).closest('summary')!
    const outputPath = `${detailPath}/diagnostic-runs/1`
    expect(requestsTo(outputPath)).toHaveLength(0)
    expect(summary).toHaveTextContent('終了コード 3')
    expect(summary).toHaveTextContent('運用者（op）')
    fireEvent.click(summary)
    expect(await screen.findByText('標準出力を切り詰めました。')).toBeVisible()
    expect(screen.getByText('標準出力の内容').tagName).toBe('PRE')
    expect(screen.getByText('標準エラーを切り詰めました。')).toBeVisible()
    expect(requestsTo(outputPath)).toHaveLength(1)
  })

  it('候補の API で対象が一意に決まらないときは先に選ばない', async () => {
    candidateTarget = null
    registeredTargets = [target]
    const dialog = await openRun()
    expect(dialog.getByLabelText('対象')).toHaveValue('')
    expect(dialog.getByRole('button', { name: 'プレビュー' })).toBeDisabled()
    expect(requestsTo(`${diagnosticPath}/preview`)).toHaveLength(0)
  })

  it('追加のコマンドは手順の外から開き、対象を自分で選ぶ', async () => {
    diagnosticsEnabled = true
    renderApp()
    fireEvent.click(await screen.findByText('ほかのコマンド'))
    fireEvent.click(screen.getByRole('button', { name: '追加のデモコマンドを実行' }))
    const dialog = within(await screen.findByRole('dialog', { name: '追加のデモコマンド' }))
    expect(dialog.getByLabelText('対象')).toHaveValue('')
    fireEvent.change(dialog.getByLabelText('対象'), { target: { value: secondTarget.id } })
    fireEvent.click(await previewRun(dialog))
    await waitFor(() => expect(submittedBody()).toMatchObject({
      command: { custom: custom.id }, target_id: secondTarget.id, params: { vmnic: 'vmnic0' },
    }))
  })

  it('手順に含まれない組み込みの vCenter コマンドも選べる', async () => {
    diagnosticsEnabled = true
    renderApp()
    fireEvent.click(await screen.findByText('ほかのコマンド'))
    fireEvent.click(screen.getByText('手順にない組み込みのコマンド'))
    fireEvent.click(screen.getByRole('button', { name: 'vCenter のサービスを実行' }))
    const dialog = within(await screen.findByRole('dialog', { name: 'vCenter のサービス' }))
    expect(dialog.getByLabelText('対象')).toHaveValue('')
    expect(dialog.getByRole('option', { name: 'デモ vCenter' })).toBeVisible()
    expect(dialog.queryByRole('option', { name: 'デモ ESXi' })).not.toBeInTheDocument()
  })

  it('一覧の検索と絞り込み、詳細への履歴追加と戻る、タブ切り替えでの書き戻し', async () => {
    window.history.replaceState(null, '', listHash)
    renderApp()
    expect(tab('タイムライン').nextElementSibling).toBe(tab('インシデント'))
    expect(tab('インシデント').querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
    const item = await screen.findByRole('link', { name: INCIDENT_TITLE })
    expect(screen.getByRole('combobox', { name: '状態' })).toHaveValue('unresolved')
    expect(screen.getByRole('columnheader', { name: '紐付け' })).toBeVisible()
    const initialHistory = window.history.length
    fireEvent.click(item)
    expect(window.history.length).toBe(initialHistory + 1)
    expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
    expect(location.hash).toBe(detailHash)
    fireEvent.click(tab('タイムライン'))
    await waitFor(() => expect(location.hash).toMatch(/^#\/timeline/))
    fireEvent.click(tab('インシデント'))
    expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
    expect(location.hash).toBe(detailHash)
    act(() => window.history.back())
    expect(await screen.findByRole('link', { name: INCIDENT_TITLE })).toBeVisible()
    expect(location.hash).toBe(listHash)
    fireEvent.change(screen.getByRole('combobox', { name: '状態' }), { target: { value: 'resolved' } })
    fireEvent.change(screen.getByRole('searchbox', { name: '件名' }), { target: { value: '切断' } })
    fireEvent.click(screen.getByRole('button', { name: '検索' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => {
      const params = new URL(String(url), location.href).searchParams
      return params.get('status') === 'resolved' && params.get('q') === '切断'
    })).toBe(true))
  })

  it('hashchange で別の詳細を開き、404 なら一覧に戻す', async () => {
    renderApp()
    expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
    act(() => { location.hash = '#/incidents/no-such-incident' })
    expect(await screen.findByRole('alert', { name: '' })).toHaveTextContent('インシデントが見つかりません')
    expect(await screen.findByRole('link', { name: INCIDENT_TITLE })).toBeVisible()
    expect(location.hash).toBe(listHash)
  })

  it.each(['viewer', 'operator', 'admin'] as const)('%s の権限で操作を表示する', async (role) => {
    renderApp(role)
    expect(await screen.findByText('管理ネットワークを調査中')).toBeVisible()
    expect(screen.getByText('再発の有無を確認')).toBeVisible()
    expect(screen.getByText('（管理者が削除しました）')).toBeVisible()
    expect(screen.getByRole('link', { name: '前後 30 分のタイムライン' })).toHaveAttribute('href', expect.stringContaining('entity_moid=host-1'))
    expect(screen.getByText('元の行は削除されています')).toBeVisible()
    expect(screen.getByRole('button', { name: 'タイムラインで開く' })).toBeVisible()
    expect(screen.queryAllByRole('button', { name: '外す' })).toHaveLength(role === 'viewer' ? 0 : 3)
    expect(screen.queryAllByRole('button', { name: '編集' })).toHaveLength(role === 'viewer' ? 0 : 1)
    expect(screen.queryAllByRole('button', { name: 'メモを追加' })).toHaveLength(role === 'viewer' ? 0 : 1)
    expect(screen.queryAllByRole('button', { name: /^削除$|^インシデントを削除$/ })).toHaveLength(role === 'admin' ? 2 : 0)
    fireEvent.click(screen.getByRole('button', { name: '一覧に戻る' }))
    await screen.findByRole('link', { name: INCIDENT_TITLE })
    expect(screen.queryAllByRole('button', { name: 'インシデントを作る' })).toHaveLength(role === 'viewer' ? 0 : 1)
  })

  it('自分を担当に指定し、incident_stale なら読み直しを案内する', async () => {
    renderApp('operator')
    fireEvent.click(await screen.findByRole('button', { name: '編集' }))
    fireEvent.click(screen.getByRole('button', { name: '自分' }))
    expect(screen.getByRole('textbox', { name: '担当' })).toHaveValue('運用者（op）')
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    expect(await screen.findByText('ほかの人が更新しました。読み直してください')).toBeVisible()
    const [, patch] = fetchMock.mock.calls.find(([url, options]) => String(url).endsWith(detailPath) && options?.method === 'PATCH')!
    expect(JSON.parse(patch.body)).toEqual({ assignee: '運用者（op）', revision: INCIDENT_DETAIL.revision })
    latest = {
      ...INCIDENT_DETAIL,
      revision: '44444444-4444-4444-8444-444444444444',
      assignee: '別の担当者',
      summary: 'ほかの人が要約を変更しました',
    }
    fireEvent.click(screen.getByRole('button', { name: '読み直す' }))
    expect(await screen.findByText('読み直した最新の内容')).toBeVisible()
    expect(screen.getByText('別の担当者')).toBeVisible()
    expect(screen.getByRole('textbox', { name: '担当' })).toHaveValue('運用者（op）')
    expect(screen.getByRole('textbox', { name: '要約' })).toHaveValue(latest.summary)
    updateStatus = 200
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    expect(await screen.findByRole('button', { name: '編集' })).toBeVisible()
    const patches = fetchMock.mock.calls.filter(([url, options]) => String(url).endsWith(detailPath) && options?.method === 'PATCH')
    expect(JSON.parse(patches[1][1].body)).toEqual({ assignee: '運用者（op）', revision: latest.revision })
  })

  it('別の 409 は競合として扱わず、認証が無効なら「自分」を表示しない', async () => {
    updateCode = 'principal_changed'
    renderApp('admin', false)
    fireEvent.click(await screen.findByRole('button', { name: '編集' }))
    expect(screen.queryByRole('button', { name: '自分' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    expect(await screen.findByText('ユーザーが切り替わりました')).toBeVisible()
    expect(screen.queryByRole('button', { name: '読み直す' })).toBeNull()
  })

  it('同じスナップショットを続けて開け、結果はハッシュの条件と分けて扱う', async () => {
    renderApp()
    for (let count = 1; count <= 2; count++) {
      fireEvent.click(await screen.findByRole('button', { name: 'タイムラインで開く' }))
      expect(await screen.findByRole('button', { name: /VmPoweredOffEvent/ })).toBeVisible()
      expect(tab('タイムライン')).toHaveClass('active')
      expect(location.hash).toMatch(/^#\/timeline\?from=/)
      expect(location.hash).not.toContain(SNAPSHOT_ID)
      expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith(snapshotPath))).toHaveLength(count)
      fireEvent.click(tab('インシデント'))
    }
    expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
  })

  it('スナップショットの 404 はタイムラインのエラー欄に表示する', async () => {
    snapshotMissing = true
    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: 'タイムラインで開く' }))
    expect(await screen.findByText('スナップショットを開けませんでした')).toHaveClass('panel-error-banner')
    expect(tab('タイムライン')).toHaveClass('active')
  })

  it('保存結果が読めなければ保存した条件で再集計し、遅れて届く書き戻しでも条件と注記を保つ', async () => {
    snapshotUnreadable = true
    const rollingHash = '#/timeline?range=1h'
    let delayed: HashChangeEvent | undefined
    let delivered = false
    // 通常の通知は止め、React が固定期間を反映して URL を書き戻す直前に通知を届ける。
    const holdRollingHash = (event: HashChangeEvent) => {
      if (!delivered && event.newURL === delayed?.newURL) event.stopImmediatePropagation()
    }
    window.addEventListener('hashchange', holdRollingHash, true)
    const replaceState = window.history.replaceState.bind(window.history)
    const replace = vi.spyOn(window.history, 'replaceState').mockImplementation((data, unused, url) => {
      const oldURL = window.location.href
      const hash = new URL(url ?? oldURL, oldURL).hash
      if (hash.startsWith('#/timeline?from=') && delayed && !delivered) {
        delivered = true
        window.dispatchEvent(delayed)
      }
      replaceState(data, unused, url)
      if (hash === rollingHash && oldURL !== window.location.href) {
        delayed = new HashChangeEvent('hashchange', { oldURL, newURL: window.location.href })
      }
    })
    try {
      renderApp()
      fireEvent.click(await screen.findByRole('button', { name: 'タイムラインで開く' }))
      const notice = /保存時点の結果はいまの形式で読めない/
      expect(await screen.findByText(notice)).toBeVisible()
      await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) =>
        String(url).endsWith('/api/incident-timeline/view') && JSON.parse(init.body).from === '2026-03-22T00:00:00.000Z')).toBe(true))
      await act(async () => { await new Promise((resolve) => window.setTimeout(resolve, 0)) })
      expect(delivered).toBe(true)
      expect(screen.getByText(notice)).toBeVisible()
      expect(location.hash).toMatch(/^#\/timeline\?from=/)
      expect(new URLSearchParams(location.hash.split('?')[1]).get('from')).toBe('2026-03-22T00:00:00.000Z')
    } finally {
      replace.mockRestore()
      window.removeEventListener('hashchange', holdRollingHash, true)
    }
  })

  it('タイムラインへ移っても編集中の項目、メモ、進行中の出力を保つ', async () => {
    let finishExport: (response: Response) => void = () => {}
    let exportSignal: AbortSignal | null | undefined
    const originalFetch = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes(`${snapshotPath}/export?`)) {
        exportSignal = init?.signal
        return new Promise<Response>((resolve) => { finishExport = resolve })
      }
      return originalFetch(input, init)
    })
    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: '編集' }))
    fireEvent.change(screen.getByRole('textbox', { name: '件名' }), { target: { value: '編集中の件名' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'メモ' }), { target: { value: '書きかけのメモ' } })
    fireEvent.click(screen.getByRole('button', { name: /調査資料を Markdown で出力/ }))
    await waitFor(() => expect(exportSignal).toBeDefined())
    fireEvent.click(screen.getByRole('button', { name: 'タイムラインで開く' }))
    expect(await screen.findByRole('button', { name: /VmPoweredOffEvent/ })).toBeVisible()
    expect(screen.queryByRole('textbox', { name: 'メモ' })).toBeNull()
    expect(exportSignal?.aborted).toBe(false)
    fireEvent.click(tab('インシデント'))
    expect(screen.getByRole('textbox', { name: '件名' })).toHaveValue('編集中の件名')
    expect(screen.getByRole('textbox', { name: 'メモ' })).toHaveValue('書きかけのメモ')
    expect(screen.getByRole('button', { name: /調査資料を Markdown で出力/ })).toHaveTextContent('出力中…')
    await act(async () => { finishExport(respond404()) })
    expect(await screen.findByText(/スナップショットが見つかりません/)).toBeVisible()
    // タブに戻ると詳細を 1 回だけ読み直し、読み直したあとも下書きを保つ
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith(detailPath))).toHaveLength(2))
    expect(screen.getByRole('textbox', { name: '件名' })).toHaveValue('編集中の件名')
    expect(screen.getByRole('textbox', { name: 'メモ' })).toHaveValue('書きかけのメモ')
  })

  it('ほかのタブから戻ると紐付けを読み直し、編集の下書きがあれば項目と revision は元のまま保つ', async () => {
    updateStatus = 200
    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: '編集' }))
    fireEvent.change(screen.getByRole('textbox', { name: '件名' }), { target: { value: '編集中の件名' } })
    const newRevision = '44444444-4444-4444-8444-444444444444'
    latest = {
      ...INCIDENT_DETAIL,
      title: 'ほかの人が変えた件名',
      revision: newRevision,
      events: [...INCIDENT_DETAIL.events, { ...INCIDENT_DETAIL.events[0], id: 2, event_id: 124, vmware_key: 1235, event_type: 'DatastoreRemovedOnHostEvent' }],
    }
    fireEvent.click(tab('イベント'))
    fireEvent.click(tab('インシデント'))
    expect(await screen.findByText('DatastoreRemovedOnHostEvent')).toBeVisible()
    expect(screen.getByRole('textbox', { name: '件名' })).toHaveValue('編集中の件名')
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(true))
    const [, patchInit] = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')!
    // 読み直す前の revision で送るので、ほかの人の変更とぶつかれば 409 になる
    expect(JSON.parse(String(patchInit?.body))).toMatchObject({ revision: INCIDENT_DETAIL.revision, title: '編集中の件名' })
  })

  it('メモを追加したあとの読み直しでも、編集の下書きがあれば revision を元のまま保つ', async () => {
    updateStatus = 200
    const newEntry = { ...INCIDENT_DETAIL.entries[0], id: 3, body: '追加したメモ' }
    const originalFetch = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith(`${detailPath}/entries`) && init?.method === 'POST') return Promise.resolve(jsonResponse(newEntry, 201))
      return originalFetch(input, init)
    })
    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: '編集' }))
    fireEvent.change(screen.getByRole('textbox', { name: '件名' }), { target: { value: '編集中の件名' } })
    latest = {
      ...INCIDENT_DETAIL,
      title: 'ほかの人が変えた件名',
      revision: '44444444-4444-4444-8444-444444444444',
      entries: [...INCIDENT_DETAIL.entries, newEntry],
    }
    fireEvent.change(screen.getByRole('textbox', { name: 'メモ' }), { target: { value: '追加したメモ' } })
    fireEvent.click(screen.getByRole('button', { name: 'メモを追加' }))
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith(detailPath) && !init?.method)).toHaveLength(2))
    expect(await screen.findByText('追加したメモ')).toBeVisible()
    expect(screen.getByRole('textbox', { name: '件名' })).toHaveValue('編集中の件名')
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(true))
    const [, patchInit] = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')!
    expect(JSON.parse(String(patchInit?.body))).toMatchObject({ revision: INCIDENT_DETAIL.revision, title: '編集中の件名' })
  })

  it('タブに戻ったときの読み直しが書き込みより遅れて届いても、書き込みの結果を古い内容で上書きしない', async () => {
    const newEntry = { ...INCIDENT_DETAIL.entries[0], id: 3, body: '追加したメモ' }
    let deferNext = false
    let finishStale: (response: Response) => void = () => {}
    const originalFetch = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith(`${detailPath}/entries`) && init?.method === 'POST') return Promise.resolve(jsonResponse(newEntry, 201))
      if (String(input).endsWith(detailPath) && !init?.method && deferNext) {
        deferNext = false
        return new Promise<Response>((resolve) => { finishStale = resolve })
      }
      return originalFetch(input, init)
    })
    renderApp()
    expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
    fireEvent.click(tab('イベント'))
    deferNext = true
    fireEvent.click(tab('インシデント'))
    await waitFor(() => expect(deferNext).toBe(false))
    latest = { ...INCIDENT_DETAIL, entries: [...INCIDENT_DETAIL.entries, newEntry] }
    fireEvent.change(screen.getByRole('textbox', { name: 'メモ' }), { target: { value: '追加したメモ' } })
    fireEvent.click(screen.getByRole('button', { name: 'メモを追加' }))
    expect(await screen.findByText('追加したメモ')).toBeVisible()
    // 書き込みの前に始めた読み直しの応答（メモが無い古い内容）を、あとから届ける
    await act(async () => { finishStale(jsonResponse(INCIDENT_DETAIL)) })
    expect(screen.getByText('追加したメモ')).toBeVisible()
  })

  it('409 のあとの読み直しで最新と同じになった項目は下書きから外し、その後の変更を古い下書きで上書きしない', async () => {
    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: '編集' }))
    fireEvent.change(screen.getByRole('textbox', { name: '件名' }), { target: { value: '同じ件名' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    expect(await screen.findByText('ほかの人が更新しました。読み直してください')).toBeVisible()
    // ほかの人も同じ件名に変えていた
    latest = { ...INCIDENT_DETAIL, title: '同じ件名', revision: '44444444-4444-4444-8444-444444444444' }
    fireEvent.click(screen.getByRole('button', { name: '読み直す' }))
    expect(await screen.findByText('読み直した最新の内容')).toBeVisible()
    // そのあと、さらにほかの人が件名を変えた
    const thirdRevision = '55555555-5555-4555-8555-555555555555'
    latest = { ...INCIDENT_DETAIL, title: '三人目の件名', revision: thirdRevision }
    fireEvent.click(tab('イベント'))
    fireEvent.click(tab('インシデント'))
    await waitFor(() => expect(screen.getByRole('textbox', { name: '件名' })).toHaveValue('三人目の件名'))
    updateStatus = 200
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    expect(await screen.findByRole('button', { name: '編集' })).toBeVisible()
    const patches = fetchMock.mock.calls.filter(([url, options]) => String(url).endsWith(detailPath) && options?.method === 'PATCH')
    expect(JSON.parse(String(patches[1][1]?.body))).toEqual({ revision: thirdRevision })
  })

  it('表示のタイムゾーンを変えて最新と同じになった開始時刻は下書きから外し、その後の変更を古い下書きで上書きしない', async () => {
    localStorage.setItem('vea.displayTimeZone', 'Asia/Tokyo')
    try {
      renderApp()
      fireEvent.click(await screen.findByRole('button', { name: '編集' }))
      // 開始時刻は 00:10Z（東京では 09:10）。東京の 00:10 に書き換える
      fireEvent.change(screen.getByLabelText('開始時刻（Asia/Tokyo）'), { target: { value: '2026-03-22T00:10' } })
      fireEvent.click(tab('設定'))
      fireEvent.click(await screen.findByRole('button', { name: '一般' }))
      fireEvent.change(await screen.findByRole('combobox', { name: '表示タイムゾーン' }), { target: { value: 'UTC' } })
      // UTC で見ると、下書きの 00:10 は最新の開始時刻と同じになる。そのあと、ほかの人が開始時刻を変えた
      const newRevision = '44444444-4444-4444-8444-444444444444'
      latest = { ...INCIDENT_DETAIL, started_at: '2026-03-22T01:10:00Z', revision: newRevision }
      fireEvent.click(tab('インシデント'))
      await waitFor(() => expect(screen.getByLabelText('開始時刻（UTC）')).toHaveValue('2026-03-22T01:10'))
      updateStatus = 200
      fireEvent.click(screen.getByRole('button', { name: '保存' }))
      expect(await screen.findByRole('button', { name: '編集' })).toBeVisible()
      const [, patchInit] = fetchMock.mock.calls.find(([url, options]) => String(url).endsWith(detailPath) && options?.method === 'PATCH')!
      expect(JSON.parse(String(patchInit?.body))).toEqual({ revision: newRevision })
    } finally {
      localStorage.removeItem('vea.displayTimeZone')
    }
  })

  it('下書きが無ければ、ほかのタブから戻ったときに詳細をすべて最新にする', async () => {
    renderApp()
    expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
    latest = { ...INCIDENT_DETAIL, title: 'ほかの人が変えた件名', revision: '44444444-4444-4444-8444-444444444444' }
    fireEvent.click(tab('イベント'))
    fireEvent.click(tab('インシデント'))
    expect(await screen.findByRole('heading', { name: 'ほかの人が変えた件名' })).toBeVisible()
  })

  it.each(['一覧に戻る', 'インシデント'] as const)('%s で一覧への履歴を追加する', async (operation) => {
    window.history.replaceState(null, '', listHash)
    renderApp()
    fireEvent.click(await screen.findByRole('link', { name: INCIDENT_TITLE }))
    await screen.findByRole('heading', { name: INCIDENT_TITLE })
    const length = window.history.length
    fireEvent.click(operation === 'インシデント' ? tab(operation) : screen.getByRole('button', { name: operation }))
    expect(await screen.findByRole('link', { name: INCIDENT_TITLE })).toBeVisible()
    expect(location.hash).toBe(listHash)
    expect(window.history.length).toBe(length + 1)
    act(() => window.history.back())
    expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
    expect(location.hash).toBe(detailHash)
  })

  it('一覧で作成した詳細からブラウザの「戻る」で一覧を開ける', async () => {
    window.history.replaceState(null, '', listHash)
    renderApp()
    await screen.findByRole('link', { name: INCIDENT_TITLE })
    fireEvent.click(screen.getByRole('button', { name: 'インシデントを作る' }))
    const form = within(screen.getByRole('dialog', { name: 'インシデントを作る' }))
    fireEvent.change(form.getByRole('textbox', { name: '件名' }), { target: { value: INCIDENT_TITLE } })
    fireEvent.click(form.getByRole('button', { name: '作成' }))
    expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
    act(() => window.history.back())
    expect(await screen.findByRole('link', { name: INCIDENT_TITLE })).toBeVisible()
    expect(location.hash).toBe(listHash)
  })

  it('404 の表示は絞り込みとタブ移動でそれぞれ消える', async () => {
    window.history.replaceState(null, '', '#/incidents/missing')
    renderApp()
    const message = 'インシデントが見つかりません'
    expect(await screen.findByText(message)).toBeVisible()
    fireEvent.change(screen.getByRole('combobox', { name: '状態' }), { target: { value: 'all' } })
    expect(screen.queryByText(message)).toBeNull()
    act(() => { location.hash = '#/incidents/missing-again' })
    expect(await screen.findByText(message)).toBeVisible()
    fireEvent.click(tab('タイムライン'))
    fireEvent.click(tab('インシデント'))
    expect(screen.queryByText(message)).toBeNull()
  })

  it('タブが切り替わると選択したタブをアニメーションなしで表示範囲に入れる', async () => {
    const scroll = vi.spyOn(HTMLElement.prototype, 'scrollIntoView')
    try {
      renderApp()
      await screen.findByRole('heading', { name: INCIDENT_TITLE })
      fireEvent.click(tab('タイムライン'))
      fireEvent.click(tab('インシデント'))
      expect(scroll.mock.instances.at(-1)).toBe(tab('インシデント'))
      expect(scroll).toHaveBeenLastCalledWith({ block: 'nearest', inline: 'nearest', behavior: 'instant' })
    } finally {
      scroll.mockRestore()
    }
  })

  it('長い表示名を短くしても「自分」のユーザー名を残す', async () => {
    renderApp('operator', true, '名'.repeat(256))
    fireEvent.click(await screen.findByRole('button', { name: '編集' }))
    fireEvent.click(screen.getByRole('button', { name: '自分' }))
    expect(screen.getByRole('textbox', { name: '担当' })).toHaveValue(`${'名'.repeat(252)}（op）`)
  })

  it('メモを保存できたら再読込に失敗しても下書きを消す', async () => {
    const originalFetch = fetchMock.getMockImplementation()!
    const body = '一度だけ追加するメモ'
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith(`${detailPath}/entries`) && init?.method === 'POST') {
        detailStatus = 503
        return Promise.resolve(jsonResponse({ ...INCIDENT_DETAIL.entries[0], id: 3, body }, 201))
      }
      return originalFetch(input, init)
    })
    renderApp()
    const note = await screen.findByRole('textbox', { name: 'メモ' })
    fireEvent.change(note, { target: { value: body } })
    fireEvent.click(screen.getByRole('button', { name: 'メモを追加' }))
    expect(await screen.findByText('メモを追加しました。最新の経過を読み込めませんでした。')).toBeVisible()
    expect(screen.getByText(body)).toBeVisible()
    expect(note).toHaveValue('')
    expect(screen.getByRole('button', { name: 'メモを追加' })).toBeDisabled()
    expect(fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith('/entries') && init?.method === 'POST')).toHaveLength(1)
  })

  it.each(['保存', 'メモを追加', 'インシデントを削除'] as const)('%s で 404 なら一覧に戻る', async (action) => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    try {
      updateStatus = 404
      renderApp()
      await screen.findByRole('heading', { name: INCIDENT_TITLE })
      if (action === '保存') fireEvent.click(screen.getByRole('button', { name: '編集' }))
      if (action === 'メモを追加') fireEvent.change(screen.getByRole('textbox', { name: 'メモ' }), { target: { value: 'メモの下書き' } })
      fireEvent.click(screen.getAllByRole('button', { name: action })[0])
      expect(await screen.findByText('インシデントが見つかりません')).toBeVisible()
      expect(await screen.findByRole('link', { name: INCIDENT_TITLE })).toBeVisible()
      expect(location.hash).toBe(listHash)
    } finally {
      confirm.mockRestore()
    }
  })

  it.each([
    ['外す', 'events', 'Incident link not found', 'すでに外されていました', false],
    ['削除', 'entries', 'Incident entry not found', 'すでに削除されていました', false],
    ['外す', 'events', 'Incident not found', 'インシデントが見つかりません', true],
  ] as const)('%s が 404 のとき、再取得の結果で %s の表示を決める', async (action, kind, serverMessage, message, missing) => {
    const originalFetch = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes(`${detailPath}/${kind}/`) && init?.method === 'DELETE') {
        latest = { ...latest, [kind]: [] }
        detailStatus = missing ? 404 : 200
        return Promise.resolve(jsonResponse({ detail: serverMessage }, 404))
      }
      return originalFetch(input, init)
    })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    try {
      renderApp()
      fireEvent.click((await screen.findAllByRole('button', { name: action }))[0])
      expect(await screen.findByText(message)).toBeVisible()
      if (missing) {
        expect(await screen.findByRole('link', { name: INCIDENT_TITLE })).toBeVisible()
        expect(location.hash).toBe(listHash)
      } else {
        expect(screen.getByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
        expect(screen.queryByText(kind === 'events' ? '接続を失いました' : INCIDENT_DETAIL.entries[0].body)).toBeNull()
        expect(location.hash).toBe(detailHash)
      }
      expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith(detailPath))).toHaveLength(2)
    } finally {
      confirm.mockRestore()
    }
  })

  it('タイムラインからタブで詳細に戻るときは履歴を増やさず、一覧への遷移だけ履歴に積む', async () => {
    window.history.replaceState(null, '', listHash)
    renderApp()
    fireEvent.click(await screen.findByRole('link', { name: INCIDENT_TITLE }))
    const openTimeline = await screen.findByRole('button', { name: 'タイムラインで開く' })
    const length = window.history.length
    fireEvent.click(openTimeline)
    await screen.findByRole('button', { name: /VmPoweredOffEvent/ })
    expect(window.history.length).toBe(length + 1)
    fireEvent.click(tab('インシデント'))
    expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
    expect(location.hash).toBe(detailHash)
    expect(window.history.length).toBe(length + 1)
    fireEvent.click(screen.getByRole('button', { name: '一覧に戻る' }))
    expect(await screen.findByRole('link', { name: INCIDENT_TITLE })).toBeVisible()
    expect(location.hash).toBe(listHash)
    expect(window.history.length).toBe(length + 2)
  })

  it.each(['タイムラインで開く', '前後 30 分のタイムライン'] as const)('%s の後にブラウザで戻ると同じ詳細と下書きに戻る', async (action) => {
    window.history.replaceState(null, '', listHash)
    renderApp()
    fireEvent.click(await screen.findByRole('link', { name: INCIDENT_TITLE }))
    fireEvent.click(await screen.findByRole('button', { name: '編集' }))
    fireEvent.change(screen.getByRole('textbox', { name: '件名' }), { target: { value: '下書きの件名' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'メモ' }), { target: { value: '下書きのメモ' } })
    if (action === 'タイムラインで開く') {
      fireEvent.click(screen.getByRole('button', { name: action }))
      await screen.findByRole('button', { name: /VmPoweredOffEvent/ })
    } else {
      const link = screen.getByRole<HTMLAnchorElement>('link', { name: action })
      act(() => { link.click() })
    }
    await waitFor(() => expect(tab('タイムライン')).toHaveClass('active'))
    act(() => window.history.back())
    expect(await screen.findByRole('textbox', { name: '件名' })).toHaveValue('下書きの件名')
    expect(screen.getByRole('textbox', { name: 'メモ' })).toHaveValue('下書きのメモ')
    expect(location.hash).toBe(detailHash)
  })

  it.each(['編集', 'メモ'] as const)('%s の下書きがあればタブの押し直しで破棄を確認する', async (draft) => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    try {
      renderApp()
      await screen.findByRole('heading', { name: INCIDENT_TITLE })
      if (draft === '編集') fireEvent.click(screen.getByRole('button', { name: '編集' }))
      const field = screen.getByRole('textbox', { name: draft === '編集' ? '件名' : 'メモ' })
      fireEvent.change(field, { target: { value: '未保存の入力' } })
      fireEvent.click(tab('インシデント'))
      expect(confirm).toHaveBeenCalledWith(expect.stringContaining('保存していない入力'))
      expect(field).toHaveValue('未保存の入力')
      expect(location.hash).toBe(detailHash)
      fireEvent.click(tab('インシデント'))
      expect(await screen.findByRole('link', { name: INCIDENT_TITLE })).toBeVisible()
      expect(location.hash).toBe(listHash)
    } finally {
      confirm.mockRestore()
    }
  })

  it('詳細の一時的な読み込みエラーから再試行できる', async () => {
    detailStatus = 503
    renderApp()
    const retry = await screen.findByRole('button', { name: '読み直す' })
    detailStatus = 200
    fireEvent.click(retry)
    expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
    expect(screen.queryByRole('button', { name: '読み直す' })).toBeNull()
  })

  it('未送信の作成ダイアログはタブ移動で閉じる', async () => {
    window.history.replaceState(null, '', listHash)
    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: 'インシデントを作る' }))
    fireEvent.click(tab('タイムライン'))
    expect(screen.queryByRole('dialog')).toBeNull()
    fireEvent.click(tab('インシデント'))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it.each(['成功', '失敗'] as const)('タブを離れている間の作成が%sしたら、一覧に戻ったときに結果を表示する', async (outcome) => {
    let finishCreate: (response: Response) => void = () => {}
    const originalFetch = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/api/incidents') && init?.method === 'POST') {
        return new Promise<Response>((resolve) => { finishCreate = resolve })
      }
      return originalFetch(input, init)
    })
    window.history.replaceState(null, '', listHash)
    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: 'インシデントを作る' }))
    const form = within(screen.getByRole('dialog'))
    fireEvent.change(form.getByRole('textbox', { name: '件名' }), { target: { value: INCIDENT_TITLE } })
    fireEvent.click(form.getByRole('button', { name: '作成' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) =>
      String(url).endsWith('/api/incidents') && init?.method === 'POST')).toBe(true))
    expect(form.getByRole('button', { name: '作成' })).toBeDisabled()
    fireEvent.click(tab('タイムライン'))
    expect(screen.queryByRole('dialog')).toBeNull()
    const error = 'インシデントを作成できませんでした'
    const response = outcome === '成功'
      ? jsonResponse({ incident: INCIDENT_DETAIL, link_results: { events: [], alerts: [], snapshots: [] } }, 201)
      : jsonResponse({ detail: error }, 409)
    await act(async () => { finishCreate(response) })
    expect(tab('タイムライン')).toHaveClass('active')
    expect(screen.queryByRole('dialog')).toBeNull()
    fireEvent.click(tab('インシデント'))
    const result = within(await screen.findByRole('dialog', { name: 'インシデントを作る' }))
    expect(location.hash).toBe(listHash)
    if (outcome === '成功') {
      expect(result.getByRole('status')).toHaveTextContent('インシデントを作成しました')
      const link = result.getByRole<HTMLAnchorElement>('link', { name: 'インシデントを開く' })
      expect(link).toHaveAttribute('href', detailHash)
      act(() => { link.click() })
      expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
      expect(location.hash).toBe(detailHash)
    } else {
      expect(result.getByRole('alert')).toHaveTextContent(error)
      expect(result.getByRole('textbox', { name: '件名' })).toHaveValue(INCIDENT_TITLE)
      expect(result.getByRole('button', { name: '作成' })).toBeEnabled()
    }
  })

  it('別タブにいる間に書き込みが 404 になったら、インシデントに戻ったときに知らせる', async () => {
    let finishNote: (response: Response) => void = () => {}
    const originalFetch = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith(`${detailPath}/entries`) && init?.method === 'POST') {
        return new Promise<Response>((resolve) => { finishNote = resolve })
      }
      return originalFetch(input, init)
    })
    renderApp()
    fireEvent.change(await screen.findByRole('textbox', { name: 'メモ' }), { target: { value: '送信中のメモ' } })
    fireEvent.click(screen.getByRole('button', { name: 'メモを追加' }))
    fireEvent.click(screen.getByRole('button', { name: 'タイムラインで開く' }))
    await screen.findByRole('button', { name: /VmPoweredOffEvent/ })
    await act(async () => { finishNote(respond404()) })
    expect(location.hash).toMatch(/^#\/timeline/)
    expect(screen.queryByText('インシデントが見つかりません')).toBeNull()
    fireEvent.click(tab('インシデント'))
    expect(await screen.findByText('インシデントが見つかりません')).toBeVisible()
    expect(location.hash).toBe(listHash)
  })

  it('結果の無いスナップショットは保存条件で再集計し、読込失敗の注記を表示しない', async () => {
    snapshotHasResult = false
    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: 'タイムラインで開く' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) =>
      String(url).endsWith('/api/incident-timeline/view') && JSON.parse(init.body).from === '2026-03-22T00:00:00.000Z')).toBe(true))
    expect(screen.queryByText(/保存時点の結果はいまの形式で読めない/)).toBeNull()
  })

})
