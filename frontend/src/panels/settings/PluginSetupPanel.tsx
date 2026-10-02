import { useEffect, useRef, useState } from 'react'
import { apiDelete, apiGet, apiPost, apiPut } from '../../api'
import { toErrorMessage } from '../../utils/errors'
import './PluginSetupPanel.css'

type Values = Record<string, unknown>
export type ConfigurationSchema = {
  type: string; title?: string; description?: string; default?: unknown; enum?: unknown[]
  properties?: Record<string, ConfigurationSchema>; items?: ConfigurationSchema
  minimum?: number; maximum?: number; minLength?: number; maxLength?: number; maxItems?: number
  minItems?: number; required?: string[]
  'x-vea-widget'?: string; 'x-vea-generated-id'?: boolean; 'x-vea-vcenter-field'?: string; 'x-vea-host-field'?: string
}
type Action = { id: string; title: string; required_for_enable: boolean }
type Draft = { config_values: Values; revision: number; tests: Record<string, { ok: boolean }> }
type Definition = { schema: ConfigurationSchema; unavailable_reason: string | null; actions: Action[]; env_locked_fields: string[]; draft: Draft | null }
type VCenter = { id: string; name: string; host: string; is_enabled: boolean }
type Key = { id: string; name: string; public_key: string }
type Connection = { id: string; name: string; host: string; port: number; username: string; credential_id: string; revision: number; approved: boolean; fingerprint: string | null; candidate_fingerprint: string | null }
type Result = { ok: boolean; checks: { id: string; label: string; ok: boolean; message: string }[]; warnings: string[]; samples: Values[]; elapsed_seconds: number; draft: Draft }

export function initialValue(schema: ConfigurationSchema): unknown {
  if (schema['x-vea-generated-id']) return typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('')
  if (schema.default !== undefined) return schema.default
  if (schema.type === 'object') return Object.fromEntries(Object.entries(schema.properties ?? {}).map(([k, s]) => [k, initialValue(s)]))
  if (schema.type === 'array') return []
  if (schema.type === 'boolean') return false
  if (schema.type === 'number' || schema.type === 'integer') return schema.minimum ?? 0
  return ''
}

function errorText(error: unknown) {
  const text = toErrorMessage(error)
  try { const value = JSON.parse(text) as { detail?: unknown }; return typeof value.detail === 'string' ? value.detail : '入力内容を確認してください。' } catch { return text }
}

function downloadPublicKey(key: Key) {
  const url = URL.createObjectURL(new Blob([key.public_key], { type: 'text/plain' }))
  const link = document.createElement('a'); link.href = url; link.download = 'ssh-public-key.pub'; link.click(); URL.revokeObjectURL(url)
}

type Phase = 'all' | 'target' | 'ssh' | 'trust'

function SSHField({ value, onChange, hostHint, phase }: { value: unknown; onChange: (v: unknown) => void; hostHint: string; phase: Phase }) {
  const [keys, setKeys] = useState<Key[]>([])
  const [connections, setConnections] = useState<Connection[]>([])
  const [editing, setEditing] = useState(false)
  const [host, setHost] = useState(hostHint)
  const [port, setPort] = useState(22)
  const [username, setUsername] = useState('')
  const [credentialId, setCredentialId] = useState('')
  const [keyName, setKeyName] = useState('ログ収集用SSH鍵')
  const [keyFile, setKeyFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [keyMethod, setKeyMethod] = useState('existing')
  const selected = connections.find(c => c.id === value)
  const selectedKey = keys.find(k => k.id === (editing ? credentialId : selected?.credential_id ?? credentialId))
  const reload = async () => {
    const [ks, cs] = await Promise.all([apiGet<Key[]>('/api/plugins/ssh/credentials'), apiGet<Connection[]>('/api/plugins/ssh/connections')])
    setKeys(ks); setConnections(cs)
    if (!ks.length) setKeyMethod('generate')
  }
  useEffect(() => { void reload().catch(e => setError(errorText(e))) }, [])
  const run = async (work: () => Promise<void>) => {
    setBusy(true); setError('')
    try { await work() } catch (e) { setError(errorText(e)) } finally { setBusy(false) }
  }
  return <div className="plugin-ssh-field">
    {phase !== 'trust' && <>
    <select aria-label="登録済みSSH接続先" value={String(value ?? '')} onChange={e => { onChange(e.target.value); setConfirmed(false) }}>
      <option value="">SSH接続先を選択</option>
      {connections.map(c => <option key={c.id} value={c.id}>{c.name} ({c.host})</option>)}
    </select>
    <button type="button" className="btn btn--gray" onClick={() => { setHost(hostHint || selected?.host || ''); setPort(selected?.port ?? 22); setUsername(selected?.username ?? ''); setCredentialId(selected?.credential_id ?? ''); setEditing(!editing) }}>接続先を追加・変更</button>
    {editing && <fieldset disabled={busy}>
      <legend>SSH接続を登録</legend>
      <p>収集中の接続先を変える場合は、新しい接続先を登録してテスト後に適用します。</p>
      <label>ホスト名<input value={host} onChange={e => setHost(e.target.value)} /></label>
      <label>SSHポート<input type="number" min={1} max={65535} value={port} onChange={e => setPort(Number(e.target.value))} /></label>
      <label>SSHユーザー名<input value={username} onChange={e => setUsername(e.target.value)} autoComplete="off" /></label>
      {keyMethod === 'existing' && <label>登録済みの鍵<select value={credentialId} onChange={e => setCredentialId(e.target.value)}><option value="">鍵を選択</option>{keys.map(k => <option key={k.id} value={k.id}>{k.name}</option>)}</select></label>}
      <label>鍵の用意方法<select value={keyMethod} onChange={e => { setKeyMethod(e.target.value); setCredentialId('') }}>
        <option value="existing">登録済みの鍵を使う</option><option value="generate">新しい鍵を生成する</option><option value="upload">秘密鍵をアップロードする</option>
      </select></label>
      {keyMethod !== 'existing' && <div>
        <label>鍵の名前<input value={keyName} onChange={e => setKeyName(e.target.value)} /></label>
        {keyMethod === 'generate' && !credentialId && <button type="button" className="btn btn--gray" onClick={() => void run(async () => {
          const key = await apiPost<Key>('/api/plugins/ssh/credentials', { name: keyName }); setCredentialId(key.id); await reload()
        })}>アプリで鍵を生成</button>}
        {keyMethod === 'upload' && !credentialId && <>
        <label>既存の秘密鍵をアップロード<input type="file" onChange={e => setKeyFile(e.target.files?.[0] ?? null)} /></label>
        <button type="button" className="btn btn--gray" disabled={!keyFile} onClick={() => void run(async () => {
          if (!keyFile || keyFile.size > 32768) throw new Error('32KiB以下の秘密鍵を選択してください。')
          const key = await apiPost<Key>('/api/plugins/ssh/credentials', { name: keyName, private_key: await keyFile.text() }); setKeyFile(null); setCredentialId(key.id); await reload()
        })}>選択した鍵を登録</button></>}
        {credentialId && <p role="status">鍵を用意しました。公開鍵を管理者へ渡してください。</p>}
      </div>}
      <button type="button" className="btn btn--gray" disabled={!host || !username || !credentialId} onClick={() => void run(async () => {
        const c = await apiPost<Connection>('/api/plugins/ssh/connections', { name: host, host, port, username, credential_id: credentialId })
        await reload(); onChange(c.id); setEditing(false); setConfirmed(false)
      })}>接続先を保存</button>
    </fieldset>}
    {selectedKey && <details><summary>管理者へ渡す公開鍵と登録依頼</summary>
      <p>対象サーバーでSSHを有効化し、SSHユーザー「{selected?.username || username}」へ次の公開鍵を登録してください。対象ログの読取権限も必要です。登録後、SSHホスト鍵のSHA-256指紋を導入担当者へ別経路でお知らせください。</p>
      <pre>{selectedKey.public_key}</pre>
      <button type="button" className="btn btn--gray" onClick={() => void navigator.clipboard.writeText(selectedKey.public_key).catch(e => setError(errorText(e)))}>公開鍵をコピー</button>
      <button type="button" className="btn btn--gray" onClick={() => downloadPublicKey(selectedKey)}>公開鍵をダウンロード</button>
      <details><summary>鍵の管理</summary><button type="button" className="btn btn--gray" onClick={() => void run(async () => { await apiDelete(`/api/plugins/ssh/credentials/${selectedKey.id}`); setCredentialId(''); await reload() })}>未使用の鍵を削除</button></details>
    </details>}
    </>}
    {phase !== 'ssh' && selected && <fieldset disabled={busy}>
      <legend>接続先のホスト鍵を確認</legend>
      <p>{selected.host}:{selected.port} / {selected.username} — {selected.approved ? '承認済み' : '承認待ち'}</p>
      {selected.fingerprint && <p>承認済み指紋: <code>{selected.fingerprint}</code></p>}
      {!selected.approved && !selected.candidate_fingerprint && <button type="button" className="btn btn--gray" onClick={() => void run(async () => { await apiPost(`/api/plugins/ssh/connections/${selected.id}/host-key`, {}); setConfirmed(false); onChange(value); await reload() })}>ホスト鍵を取得</button>}
      {selected.candidate_fingerprint && (!selected.approved || selected.candidate_fingerprint !== selected.fingerprint) && <>
        <p>取得した指紋: <code>{selected.candidate_fingerprint}</code></p>
        <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />管理者から入手した指紋と一致することを確認しました</label>
        <button type="button" className="btn btn--gray" disabled={!confirmed} onClick={() => void run(async () => { await apiPost(`/api/plugins/ssh/connections/${selected.id}/approve`, { fingerprint: selected.candidate_fingerprint, revision: selected.revision }); onChange(value); await reload() })}>このホスト鍵を承認</button>
      </>}
      <details><summary>ホスト鍵を再確認する</summary><button type="button" className="btn btn--gray" onClick={() => void run(async () => { await apiPost(`/api/plugins/ssh/connections/${selected.id}/host-key`, {}); setConfirmed(false); onChange(value); await reload() })}>ホスト鍵を再取得</button></details>
    </fieldset>}
    {phase === 'trust' && !selected && <p role="alert">前の手順でSSH接続先を選択してください。</p>}
    {error && <p role="alert">{error}</p>}
  </div>
}

function HostField({ value, onChange, vcenterId, vcenters }: { value: unknown; onChange: (v: unknown) => void; vcenterId: string; vcenters: VCenter[] }) {
  const [hosts, setHosts] = useState<{ id: string; name: string; host: string }[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { setHosts([]); setError('') }, [vcenterId])
  const vc = vcenters.find(v => v.id === vcenterId)
  return <div>
    <button type="button" className="btn btn--gray" disabled={!vc || busy} onClick={() => {
      setBusy(true); setError(''); void apiGet<typeof hosts>(`/api/plugins/vcenters/${vcenterId}/hosts`).then(setHosts).catch(e => setError(errorText(e))).finally(() => setBusy(false))
    }}>ESXi一覧を取得・再試行</button>
    <select aria-label="収集ホストの候補" value={String(value ?? '')} onChange={e => onChange(e.target.value)}>
      <option value="">候補から選択、または手入力</option>
      {vc && <option value={vc.host}>{vc.name}（vCenter自身）</option>}
      {hosts.map(h => <option key={h.id} value={h.host}>{h.name}</option>)}
    </select>
    <input aria-label="接続するホスト名" value={String(value ?? '')} onChange={e => onChange(e.target.value)} />
    {error && <p role="alert">{error}</p>}
  </div>
}

export function SchemaFields({ schema, value, onChange, vcenters, siblings = {}, label = '設定', phase = 'all' }: {
  schema: ConfigurationSchema; value: unknown; onChange: (v: unknown) => void; vcenters: VCenter[]; siblings?: Values; label?: string; phase?: Phase
}) {
  if (schema['x-vea-generated-id']) return null
  const title = schema.title ?? label
  if (schema.type === 'object') {
    const object = (value ?? {}) as Values
    return <div>{Object.entries(schema.properties ?? {}).map(([key, child]) => <SchemaFields key={key} schema={child} value={object[key]} siblings={object} vcenters={vcenters} label={key} phase={phase} onChange={v => onChange({ ...object, [key]: v })} />)}</div>
  }
  if (schema.type === 'array') {
    const items = (value ?? []) as unknown[]
    const hostField = Object.values(schema.items?.properties ?? {}).find(s => s['x-vea-widget'] === 'ssh-connection')?.['x-vea-host-field']
    return <div className="plugin-setup-targets">{phase === 'target' && <h4>{title}</h4>}{items.map((item, index) => <fieldset key={typeof item === 'object' && item && 'id' in item ? String(item.id) : index}>
      <legend>{title} {index + 1}{phase !== 'target' && hostField && item && typeof item === 'object' && (item as Values)[hostField] ? ` · ${String((item as Values)[hostField])}` : ''}</legend>
      <SchemaFields schema={schema.items!} value={item} vcenters={vcenters} phase={phase} onChange={v => onChange(items.map((old, i) => i === index ? v : old))} />
      {(phase === 'target' || phase === 'all') && <details><summary>この対象の操作</summary><button type="button" className="btn btn--gray" onClick={() => onChange(items.filter((_, i) => i !== index))}>この項目を削除</button></details>}
    </fieldset>)}{(phase === 'target' || phase === 'all') && <button type="button" className="btn btn--gray" disabled={items.length >= (schema.maxItems ?? 100)} onClick={() => onChange([...items, initialValue(schema.items!)])}>{title}を追加</button>}</div>
  }
  const widget = schema['x-vea-widget']
  if (widget === 'ssh-connection') return phase === 'target' ? null : <div><h4>{title}</h4><SSHField phase={phase} value={value} onChange={onChange} hostHint={String(siblings[schema['x-vea-host-field'] ?? 'host'] ?? '')} /></div>
  if (phase === 'ssh' || phase === 'trust') return null
  if (widget === 'esxi-host') return <div><h4>{title}</h4><HostField value={value} onChange={onChange} vcenters={vcenters} vcenterId={String(siblings[schema['x-vea-vcenter-field'] ?? 'vcenter_id'] ?? '')} /></div>
  if (widget === 'vcenter') return <label>{title}<select value={String(value ?? '')} onChange={e => onChange(e.target.value)}><option value="">vCenterを選択</option>{vcenters.filter(v => v.is_enabled).map(v => <option key={v.id} value={v.id}>{v.name}</option>)}</select></label>
  if (schema.enum) return <label>{title}<select value={String(value ?? '')} onChange={e => onChange(schema.enum!.find(v => String(v) === e.target.value))}><option value="">選択してください</option>{schema.enum.map(v => <option key={String(v)} value={String(v)}>{String(v)}</option>)}</select></label>
  if (schema.type === 'boolean') return <label><input type="checkbox" checked={Boolean(value)} onChange={e => onChange(e.target.checked)} />{title}</label>
  const numeric = schema.type === 'number' || schema.type === 'integer'
  return <label>{title}<input type={numeric ? 'number' : 'text'} value={String(value ?? '')} min={schema.minimum} max={schema.maximum} step={schema.type === 'integer' ? 1 : 'any'} minLength={schema.minLength} maxLength={schema.maxLength} onChange={e => onChange(numeric ? Number(e.target.value) : e.target.value)} />{schema.description && <small>{schema.description}</small>}</label>
}

export default function PluginSetupPanel({ pluginId, onApplied, onClose, dataKinds = [] }: { pluginId: string; onApplied: () => Promise<void>; onClose?: () => void; dataKinds?: string[] }) {
  const base = `/api/plugins/collectors/${encodeURIComponent(pluginId)}`
  const [definition, setDefinition] = useState<Definition | null>(null)
  const [vcenters, setVcenters] = useState<VCenter[]>([])
  const [draft, setDraft] = useState<Draft | null>(null)
  const [values, setValues] = useState<Values>({})
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [result, setResult] = useState<Result | null>(null)
  const [step, setStep] = useState(0)
  const [completed, setCompleted] = useState(false)
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => { heading.current?.focus() }, [step, completed])
  useEffect(() => {
    let alive = true
    void Promise.all([apiGet<Definition>(`${base}/configuration`), apiGet<VCenter[]>('/api/vcenters')]).then(([d, vcs]) => {
      if (!alive) return
      setDefinition(d); setVcenters(vcs); setDraft(d.draft); setValues(d.draft?.config_values ?? initialValue(d.schema) as Values)
    }).catch(e => { if (alive) setError(errorText(e)) })
    return () => { alive = false }
  }, [base])
  const run = async (work: () => Promise<void>) => {
    setBusy(true); setError(''); setNotice('')
    try { await work() } catch (e) { setError(errorText(e)) } finally { setBusy(false) }
  }
  const save = async () => {
    const saved = await apiPut<Draft>(`${base}/draft`, { config_values: values, revision: draft?.revision })
    setDraft(saved); setDirty(false); return saved
  }
  if (definition?.unavailable_reason) return <p>{definition.unavailable_reason}</p>
  const hasSSH = Boolean(definition && JSON.stringify(definition.schema).includes('"ssh-connection"'))
  const locked = Boolean(definition?.env_locked_fields.length)
  const required = definition?.actions.filter(a => a.required_for_enable) ?? []
  const ready = Boolean(draft && !dirty && required.every(a => draft.tests[a.id]?.ok))
  const steps = hasSSH ? ['収集対象', 'SSH接続', 'ホスト鍵の確認', 'テストと開始'] : ['設定項目', 'テストと開始']
  const lastStep = steps.length - 1
  const phase: Phase = hasSSH ? (['target', 'ssh', 'trust'] as Phase[])[step] ?? 'all' : 'target'
  const descriptions = hasSSH ? [
    'まず1台を選んでください。接続先は次の手順で設定します。',
    '登録済みの接続先を選ぶか、新しく登録してください。新しい公開鍵は管理者へ渡します。',
    '表示される指紋を管理者から受け取った指紋と照合して承認してください。',
    '接続テストに成功したら収集を開始できます。試し読みは任意です。',
  ] : ['設定項目を入力してください。', '必要なテストを確認してから収集を開始します。']
  const nextAction = required.find(a => !draft?.tests[a.id]?.ok) ?? (dirty ? required[0] : undefined)
  const execute = async (action: Action) => {
    const saved = await save()
    const response = await apiPost<Result>(`${base}/draft/actions/${encodeURIComponent(action.id)}`, { revision: saved.revision })
    setResult(response); setDraft(response.draft)
  }
  const next = async () => {
    // Check just the visible stage; SSH approval is validated on entering tests.
    const check = (schema: ConfigurationSchema, value: unknown, requiredField = false): void => {
      if (schema['x-vea-generated-id']) return
      const ssh = schema['x-vea-widget'] === 'ssh-connection'
      if ((phase === 'target' && ssh) || (phase === 'ssh' && !ssh && schema.type !== 'object' && schema.type !== 'array')) return
      if ((requiredField || schema.minLength || schema.minItems) && (value === '' || value === undefined || value === null || (Array.isArray(value) && value.length < (schema.minItems ?? 1)))) throw new Error(`${schema.title ?? '項目'}を入力・選択してください。`)
      if (schema.type === 'object') for (const [key, child] of Object.entries(schema.properties ?? {})) check(child, (value as Values | undefined)?.[key], schema.required?.includes(key))
      if (schema.type === 'array') for (const item of (value as unknown[] ?? [])) check(schema.items!, item)
    }
    check(definition!.schema, values)
    await save()
    if (step + 1 === lastStep) await apiPost(`${base}/draft/validate`, {})
    setStep(step + 1); setResult(null)
  }
  const apply = async () => {
    await apiPost(`${base}/draft/apply`, { revision: draft!.revision })
    await onApplied(); setCompleted(true)
  }
  const destination = dataKinds.includes('log') ? ['#/logs', 'ログ画面を開く'] : dataKinds.includes('metric') ? ['#/metrics', 'メトリクス画面を開く'] : dataKinds.includes('event') ? ['#/events', 'イベント画面を開く'] : null
  if (completed) return <section className="plugin-setup-panel" aria-label="プラグインの導入設定">
    <h3 ref={heading} tabIndex={-1}>収集を開始しました</h3><p>設定を適用しました。定期収集の実行状況を確認できます。</p>
    {destination && <a className="btn" href={destination[0]}>{destination[1]}</a>}
    <button type="button" className="btn btn--gray" onClick={() => { setCompleted(false); setStep(0) }}>設定を見直す</button>
  </section>
  return <section className="plugin-setup-panel" aria-label="プラグインの導入設定">
    <ol className="plugin-setup-steps" aria-label="設定の進捗">{steps.map((title, i) => <li key={title} aria-current={i === step ? 'step' : undefined} data-complete={i < step}><span>{i < step ? '✓' : i + 1}</span>{title}</li>)}</ol>
    <h3 ref={heading} tabIndex={-1}>{steps[step]}</h3>
    <p>{descriptions[step]}</p>
    <p className="hint">「次へ」で下書きを保存します。収集を開始するまで稼働中の設定は変わりません。</p>
    {locked && <p>環境変数で固定されています。管理者に設定の確認を依頼してください。</p>}
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {definition && <fieldset disabled={busy || locked}>
      {step < lastStep && <SchemaFields phase={phase} schema={definition.schema} value={values} vcenters={vcenters} onChange={v => { setValues(v as Values); setDirty(true); setResult(null) }} />}
      {step === lastStep && <>
        <p className="plugin-setup-check-state" role="status">{ready ? '✓ 必須の確認は完了しました。収集を開始できます。' : '接続を確認してから収集を開始します。'}</p>
        <details><summary>入力した設定を確認する</summary><SchemaFields phase="target" schema={definition.schema} value={values} vcenters={vcenters} onChange={v => { setValues(v as Values); setDirty(true); setResult(null); setStep(0) }} /></details>
        {definition.actions.some(a => !a.required_for_enable) && <details><summary>試し読み・追加の確認（任意）</summary>
          <div className="plugin-settings-actions">{definition.actions.filter(a => !a.required_for_enable).map(a => <button key={a.id} type="button" className="btn btn--gray" onClick={() => void run(() => execute(a))}>{a.title}</button>)}</div>
        </details>}
      </>}
      <details className="plugin-setup-extra"><summary>その他の操作</summary>
        <button type="button" className="btn btn--gray" onClick={() => void run(async () => { await save(); setNotice('下書きを保存しました。'); onClose?.() })}>下書きを保存して中断</button>
        <button type="button" className="btn btn--gray" onClick={() => void run(async () => { const d = await apiPost<Draft>(`${base}/draft/import`, {}); setDraft(d); setValues(d.config_values); setDirty(false); setResult(null); setStep(0); setNotice('現在の設定を下書きへ読み込みました。SSH鍵は自動で取り込みません。') })}>現在の設定を下書きへ読み込む</button>
      </details>
    </fieldset>}
    {busy && <p role="status">処理中です…</p>}
    {result && <div><p>確認結果: {result.ok ? '成功' : '要対応'} / {result.elapsed_seconds}秒</p>
      <ul>{result.checks.map((c, i) => <li key={`${c.id}-${i}`}>{c.ok ? '✓' : '✕'} {c.label}: {c.message}</li>)}</ul>
      {result.warnings.map((w, i) => <p key={i}>{w}</p>)}
      {result.samples.length > 0 && <details open><summary>取得例</summary>{result.samples.map((sample, i) => <pre key={i}>{Object.entries(sample).map(([k, v]) => `${k}: ${String(v ?? '未解析')}`).join('\n')}</pre>)}</details>}
    </div>}
    {definition && <div className="plugin-setup-footer">
      {step > 0 && <button type="button" className="btn btn--gray" disabled={busy} onClick={() => { setStep(step - 1); setError(''); setResult(null) }}>戻る</button>}
      <button type="button" className="btn" disabled={busy || locked || (step === lastStep && !ready && !nextAction)} onClick={() => void run(step < lastStep ? next : ready ? apply : () => execute(nextAction!))}>
        {busy ? '処理中…' : step < lastStep ? '次へ' : ready ? '収集を開始' : nextAction?.title ?? '設定を確認してください'}
      </button>
    </div>}
  </section>
}
