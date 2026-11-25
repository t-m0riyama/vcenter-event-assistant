import { useEffect, useRef, useState } from 'react'
import { apiGet, apiPost, apiPut } from '../../api'
import { errorText } from './setupError'
import { SSHField } from './SSHField'
import { initialValue, type ConfigurationSchema } from './pluginConfiguration'
import './PluginSetupPanel.css'

export type { ConfigurationSchema } from './pluginConfiguration'

type Values = Record<string, unknown>
type Action = { id: string; title: string; required_for_enable: boolean }
type Draft = { config_values: Values; revision: number; tests: Record<string, { ok: boolean }> }
type Definition = { schema: ConfigurationSchema; unavailable_reason: string | null; actions: Action[]; env_locked_fields: string[]; draft: Draft | null }
type VCenter = { id: string; name: string; host: string; is_enabled: boolean }
type Result = { ok: boolean; checks: { id: string; label: string; ok: boolean; message: string }[]; warnings: string[]; samples: Values[]; elapsed_seconds: number; draft: Draft }

type Phase = 'all' | 'target' | 'ssh' | 'trust'

const pluginSshCopy = {
  keyName: 'ログ収集用SSH鍵',
  connectionHint: '収集中の接続先を変える場合は、新しい接続先を登録してテスト後に適用します。',
  registrationRequest: (username: string) =>
    `対象サーバーでSSHを有効化し、SSHユーザー「${username}」へ次の公開鍵を登録してください。対象ログの読取権限も必要です。登録後、SSHホスト鍵のSHA-256指紋を導入担当者へ別経路でお知らせください。`,
}

function HostField({ value, onChange, vcenterId, vcenters }: { value: unknown; onChange: (v: unknown) => void; vcenterId: string; vcenters: VCenter[] }) {
  const [hosts, setHosts] = useState<{ id: string; name: string; host: string }[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
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
  if (widget === 'ssh-connection') return phase === 'target' ? null : <div><h4>{title}</h4><SSHField apiPath="/api/plugins/ssh" copy={pluginSshCopy} phase={phase} value={value} onChange={onChange} hostHint={String(siblings[schema['x-vea-host-field'] ?? 'host'] ?? '')} /></div>
  if (phase === 'ssh' || phase === 'trust') return null
  if (widget === 'esxi-host') return <div><h4>{title}</h4><HostField key={String(siblings[schema['x-vea-vcenter-field'] ?? 'vcenter_id'] ?? '')} value={value} onChange={onChange} vcenters={vcenters} vcenterId={String(siblings[schema['x-vea-vcenter-field'] ?? 'vcenter_id'] ?? '')} /></div>
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
