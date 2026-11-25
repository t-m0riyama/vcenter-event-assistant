import { useEffect, useRef, useState, type RefObject } from 'react'
import { ApiError } from '../../api'
import { diagnosticTargetApi, fetchDiagnosticHosts } from '../../api/diagnostics'
import type { DiagnosticHost, DiagnosticTarget, DiagnosticTargetInput } from '../../api/schemas/diagnostics'
import type { SSHConnection } from '../../api/schemas/sshSetup'
import type { VCenter } from '../../api/schemas/vcenters'
import { SettingsListRow } from '../../components/SettingsListRow'
import { DiagnosticSettingForm } from './DiagnosticSettingForm'
import type { SSHConnectionsState } from './SSHField'
import { errorText } from './setupError'
import { diagnosticProductLabels, useDiagnosticSettings } from './useDiagnosticSettings'

type ReloadSSH = () => Promise<SSHConnection[] | undefined>

type HostSelection = Pick<DiagnosticTargetInput, 'product' | 'host_moid' | 'host_name'>
const hostValue = (host: HostSelection) => host.product === 'vcenter' ? 'vcenter' : `esxi:${host.host_moid}`

function DiagnosticHostPicker({ vcenter, host, onChange }: {
  vcenter: VCenter
  host: HostSelection | null
  onChange: (host: HostSelection | null) => void
}) {
  const [hosts, setHosts] = useState<DiagnosticHost[]>([])
  const [status, setStatus] = useState<'idle' | 'loading' | 'loaded' | 'error'>('idle')
  const [error, setError] = useState('')
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])

  const loadHosts = async () => {
    const controller = new AbortController()
    request.current = controller
    setStatus('loading')
    try {
      const result = await fetchDiagnosticHosts(vcenter.id, controller.signal)
      if (controller.signal.aborted) return
      setHosts(result)
      setStatus('loaded')
    } catch (e) {
      if (controller.signal.aborted) return
      setError(e instanceof ApiError && e.status === 422
        && typeof e.detail === 'string' && e.detail.trim() && !e.detail.includes('手入力')
        ? e.detail
        : 'ESXi 一覧を取得できません。vCenter の接続設定・参照権限を確認し、再試行してください。')
      setStatus('error')
    }
  }

  const candidates: HostSelection[] = [
    { product: 'vcenter', host_moid: null, host_name: vcenter.name },
    ...hosts.map((item): HostSelection => ({ product: 'esxi', host_moid: item.id, host_name: item.name })),
  ]
  if (host && !candidates.some(candidate => hostValue(candidate) === hostValue(host))) {
    candidates.push(host)
  }

  return <>
    <button type="button" className="btn btn--gray diagnostic-grid-action" disabled={!vcenter.is_enabled || status === 'loading'} onClick={() => void loadHosts()}>
      ESXi 一覧を取得
    </button>
    {status === 'loading' && <p className="diagnostic-wide" role="status">ESXi 一覧を読み込み中です…</p>}
    {status === 'loaded' && hosts.length === 0 && <p className="hint diagnostic-wide">この vCenter に ESXi は見つかりませんでした。</p>}
    {status === 'error' && <p className="error-banner diagnostic-wide" role="alert">{error}</p>}
    <label>製品とホスト
      <select required value={host ? hostValue(host) : ''} onChange={e => onChange(candidates.find(candidate => hostValue(candidate) === e.target.value) ?? null)}>
        <option value="">実行の対象を選択</option>
        {candidates.map(candidate => <option key={hostValue(candidate)} value={hostValue(candidate)}>
          {candidate.product === 'vcenter' ? `${candidate.host_name}（vCenter 自身）` : candidate.host_name}
        </option>)}
      </select>
    </label>
  </>
}

function TargetEditor({ row, vcenters, ssh, reloadSSH, settings }: {
  row: DiagnosticTarget | null
  vcenters: VCenter[]
  ssh: SSHConnectionsState
  reloadSSH: ReloadSSH
  settings: ReturnType<typeof useTargetSettings>
}) {
  const [refreshing, setRefreshing] = useState(false)
  const [vcenterId, setVCenterId] = useState(row?.vcenter_id ?? '')
  const [host, setHost] = useState<HostSelection | null>(row ? {
    product: row.product, host_moid: row.host_moid, host_name: row.host_name,
  } : null)
  const [connectionId, setConnectionId] = useState(row?.ssh_connection_id ?? '')
  const vcenter = vcenters.find(vc => vc.id === vcenterId)
  const connections = ssh.status === 'ready' ? ssh.connections : []
  const connection = connections.find(item => item.id === connectionId)
  const canSave = Boolean(vcenter && host && connection)
  const referenceMissing = settings.errorCode === 'diagnostic_reference_missing'
  const title = row ? '実行の対象を変更' : '実行の対象を追加'

  const refreshReferences = async () => {
    setRefreshing(true)
    try {
      const [fresh, freshConnections] = await Promise.all([settings.fetchList(), reloadSSH()])
      if (fresh && !fresh.vcenters.some(item => item.id === vcenterId)) {
        setVCenterId('')
        setHost(null)
      }
      if (freshConnections && !freshConnections.some(item => item.id === connectionId)) {
        setConnectionId('')
      }
      if (fresh && freshConnections) settings.clearError()
    } finally {
      setRefreshing(false)
    }
  }

  return <DiagnosticSettingForm title={title} editing={row !== null} busy={settings.busy || refreshing} conflict={settings.conflict}
    error={settings.error} errorAction={referenceMissing &&
      <button type="button" className="btn btn--gray" disabled={refreshing || settings.busy || ssh.status === 'loading'}
        onClick={() => void refreshReferences()}>一覧を読み直す</button>
    } canSave={canSave} onClose={settings.close} onReload={settings.reload} onDelete={settings.remove}
    onSubmit={() => {
      if (host) settings.save({ ...host, vcenter_id: vcenterId, ssh_connection_id: connectionId })
    }}>
    <div className="form-grid">
      <label>vCenter
        <select required value={vcenterId} onChange={e => { setVCenterId(e.target.value); setHost(null) }}>
          <option value="">vCenter を選択</option>
          {vcenters.filter(vc => vc.is_enabled || vc.id === row?.vcenter_id).map(vc =>
            <option key={vc.id} value={vc.id}>{vc.name}{!vc.is_enabled && '（無効）'}</option>,
          )}
        </select>
      </label>
      {vcenter && <DiagnosticHostPicker key={vcenter.id} vcenter={vcenter} host={host} onChange={setHost} />}
      <label>診断用の SSH 接続先
        <select required disabled={ssh.status !== 'ready'} value={connectionId} onChange={e => setConnectionId(e.target.value)}>
          <option value="">接続先を選択</option>
          {connections.map(item => <option key={item.id} value={item.id}>
            {item.name}（{item.username}@{item.host}:{item.port}{!item.approved && '、ホスト鍵の承認待ち'}）
          </option>)}
        </select>
      </label>
    </div>
    {ssh.status === 'loading' && <p role="status">SSH 接続先を読み込み中です…</p>}
    {ssh.status === 'error' && <p className="hint">SSH 接続先の取得に失敗しました。「SSH の鍵と接続先」で再取得してください。</p>}
    {ssh.status === 'ready' && connections.length === 0 && <p className="hint">先に「SSH の鍵と接続先」で接続先を登録してください。</p>}
  </DiagnosticSettingForm>
}

function targetError(error: unknown) {
  if (error instanceof ApiError && error.status === 409) {
    if (error.errorCode === 'diagnostic_target_duplicate') {
      return 'この vCenter・ESXi には実行の対象がすでにあります。'
    }
  }
  return errorText(error)
}

function useTargetSettings(heading: RefObject<HTMLHeadingElement | null>) {
  return useDiagnosticSettings<DiagnosticTarget, DiagnosticTargetInput, Awaited<ReturnType<typeof diagnosticTargetApi.fetch>>>(diagnosticTargetApi, heading, targetError)
}

export function DiagnosticTargets({ ssh, reloadSSH }: { ssh: SSHConnectionsState; reloadSSH: ReloadSSH }) {
  const heading = useRef<HTMLHeadingElement>(null)
  const settings = useTargetSettings(heading)
  const { data, busy, editor, listError, notice } = settings

  return <section className="panel" aria-labelledby="diagnostic-targets-title">
    <h2 id="diagnostic-targets-title" tabIndex={-1} ref={heading}>実行の対象</h2>
    <p className="hint">vCenter または配下の ESXi に、診断用の SSH 接続先を結び付けます。</p>
    {notice && <p role="status">{notice}</p>}
    {listError && <p className="error-banner" role="alert">{listError}</p>}
    {!editor && listError && <button type="button" className="btn btn--gray" disabled={busy} onClick={settings.reload}>対象の一覧を再取得</button>}
    {!data ? !listError && <p role="status">対象の一覧を読み込み中です…</p>
      : <>
        <button type="button" className="btn btn--gray" hidden={editor !== null} disabled={busy || editor !== null}
          onClick={e => settings.open(null, e.currentTarget)}>実行の対象を追加</button>
        {editor && <TargetEditor row={editor.row} vcenters={data.vcenters} ssh={ssh} reloadSSH={reloadSSH} settings={settings} />}
        {data.items.length === 0
          ? <p className="hint">実行の対象は未登録です。</p>
          : <ul className="settings-list">
            {data.items.map(row => {
              const vc = data.vcenters.find(item => item.id === row.vcenter_id)
              const connection = ssh.status === 'ready' ? ssh.connections.find(item => item.id === row.ssh_connection_id) : undefined
              const connectionText = connection
                ? `${connection.username}@${connection.host}:${connection.port}`
                : ssh.status === 'ready' ? 'SSH 接続先を確認できません'
                : ssh.status === 'error' ? 'SSH 接続先の取得に失敗' : 'SSH 接続先を取得中'
              const product = diagnosticProductLabels[row.product]
              return <SettingsListRow key={row.id} title={row.host_name}
                ariaLabel={`${row.host_name}、${product}`}
                preview={`${product} · ${vc?.name ?? row.vcenter_id} · ${connectionText}`}>
                <button type="button" className="btn btn--gray" disabled={busy || Boolean(editor)} onClick={e => settings.open(row, e.currentTarget)}>変更・削除</button>
              </SettingsListRow>
            })}
          </ul>}
      </>}
  </section>
}
