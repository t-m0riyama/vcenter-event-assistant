import { useRef, useState, type RefObject } from 'react'
import { ApiError } from '../../api'
import { diagnosticCommandApi } from '../../api/diagnostics'
import {
  diagnosticProductSchema, diagnosticTemplateErrorSchema, type DiagnosticCommand, type DiagnosticCommandInput,
} from '../../api/schemas/diagnostics'
import { SettingsListRow } from '../../components/SettingsListRow'
import { DiagnosticSettingForm } from './DiagnosticSettingForm'
import { errorText } from './setupError'
import { diagnosticProductLabels, useDiagnosticSettings } from './useDiagnosticSettings'

const maxParameters = 8
const templateErrors = {
  control_character: () => '雛形に改行や制御文字を含めることはできません。',
  undefined_parameter: (subject: string) => `${subject}が雛形の差し込み口に使われていますが、定義されていません。`,
  unused_parameter: (subject: string) => `${subject}が雛形で使われていません。`,
  dollar_prefix: (subject: string) => `${subject}の差し込み口の直前に $ は置けません。`,
  backslash_prefix: (subject: string) => `${subject}の差し込み口の直前にバックスラッシュは置けません。`,
  invalid_parameter_name: (subject: string) => `${subject}の名前は小文字の英字で始め、半角の小文字英字・数字・アンダースコアで32文字以内にしてください。`,
  duplicate_parameter: (subject: string) => `${subject}の名前が重複しています。`,
  unknown_parameter_type: (subject: string) => `${subject}の種類を一覧から選んでください。`,
  too_many_parameters: () => '引数は8個までです。',
}

const parameterExamples: Readonly<Record<string, string>> = {
  vmnic: 'vmnic0',
  vmk: 'vmk0',
  ipv4: '192.0.2.10',
  device: 'naa.…、t10.…',
}

function commandError(error: unknown) {
  if (error instanceof ApiError && error.status === 422 && error.errorCode === 'diagnostic_template_invalid') {
    const result = diagnosticTemplateErrorSchema.safeParse(error.detail)
    if (!result.success) return '雛形または引数の定義を確認してください。'
    const { reason, parameter } = result.data
    return templateErrors[reason](parameter?.trim() ? `引数「${parameter}」` : '引数')
  }
  return errorText(error)
}

function useCommandSettings(heading: RefObject<HTMLHeadingElement | null>) {
  return useDiagnosticSettings<DiagnosticCommand, DiagnosticCommandInput, Awaited<ReturnType<typeof diagnosticCommandApi.fetch>>>(
    diagnosticCommandApi, heading, commandError,
  )
}

function CommandEditor({ row, parameterTypes, settings }: {
  row: DiagnosticCommand | null
  parameterTypes: string[]
  settings: ReturnType<typeof useCommandSettings>
}) {
  const [draft, setDraft] = useState<DiagnosticCommandInput>(() => row ? {
    product: row.product,
    title: row.title,
    description: row.description,
    template: row.template,
    param_definitions: row.param_definitions,
  } : { product: 'esxi', title: '', description: '', template: '', param_definitions: [] })
  const params = draft.param_definitions
  const setParams = (param_definitions: DiagnosticCommandInput['param_definitions']) => setDraft({ ...draft, param_definitions })
  const title = row ? '追加のコマンドを変更' : 'コマンドを追加'

  return <DiagnosticSettingForm title={title} editing={row !== null} busy={settings.busy} conflict={settings.conflict}
    error={settings.error} onClose={settings.close} onReload={settings.reload} onDelete={settings.remove}
    onSubmit={() => settings.save(draft)}>
    <div className="form-grid">
      <label>製品
        <select value={draft.product} onChange={e => setDraft({ ...draft, product: diagnosticProductSchema.parse(e.target.value) })}>
          {diagnosticProductSchema.options.map(product => <option key={product} value={product}>{diagnosticProductLabels[product]}</option>)}
        </select>
      </label>
      <label>名前<input required maxLength={100} value={draft.title} onChange={e => setDraft({ ...draft, title: e.target.value })} /></label>
      <label className="diagnostic-wide">説明<textarea rows={2} maxLength={1000} value={draft.description} onChange={e => setDraft({ ...draft, description: e.target.value })} /></label>
      <label className="diagnostic-wide">コマンドの雛形<input required maxLength={1000} value={draft.template} onChange={e => setDraft({ ...draft, template: e.target.value })} /></label>
    </div>
    <p className="hint">引数の差し込み口は <code>{'{{名前}}'}</code> と書きます。</p>
    <h3>引数</h3>
    {params.map((parameter, index) => <div key={index} className="form-grid">
      <label>引数 {index + 1} の名前
        <input required value={parameter.name} onChange={e => setParams(params.map((p, i) => i === index ? { ...p, name: e.target.value } : p))} />
      </label>
      <label>引数 {index + 1} の種類
        <select required value={parameter.type} onChange={e => setParams(params.map((p, i) => i === index ? { ...p, type: e.target.value } : p))}>
          <option value="">種類を選択</option>
          {parameterTypes.map(type => <option key={type} value={type}>{type}{parameterExamples[type] && `（例: ${parameterExamples[type]}）`}</option>)}
        </select>
      </label>
      <button type="button" className="btn btn--gray diagnostic-grid-action" aria-label={`引数 ${index + 1} を削除`} onClick={() => setParams(params.filter((_, i) => i !== index))}>削除</button>
    </div>)}
    <button type="button" className="btn btn--gray" disabled={params.length >= maxParameters || parameterTypes.length === 0}
      onClick={() => setParams([...params, { name: '', type: '' }])}>引数を追加</button>
    <span className="hint"> {params.length} / {maxParameters} 個</span>
  </DiagnosticSettingForm>
}

function CommandDetails({ row }: { row: DiagnosticCommandInput }) {
  return <>
    {row.description && <p>{row.description}</p>}
    <pre>{row.template}</pre>
    {row.param_definitions.length > 0 && <ul>{row.param_definitions.map(parameter =>
      <li key={parameter.name}><code>{parameter.name}</code>（{parameter.type}）</li>,
    )}</ul>}
  </>
}

export function DiagnosticCommands() {
  const heading = useRef<HTMLHeadingElement>(null)
  const settings = useCommandSettings(heading)
  const { data, editor, busy, listError, notice } = settings
  return <section className="panel" aria-labelledby="diagnostic-commands-title">
    <h2 id="diagnostic-commands-title" tabIndex={-1} ref={heading}>追加のコマンド</h2>
    <p className="hint">追加のコマンドが読み取り専用かどうかは本体では確かめません。</p>
    {notice && <p role="status">{notice}</p>}
    {listError && <p className="error-banner" role="alert">{listError}</p>}
    {!editor && listError && <button type="button" className="btn btn--gray" disabled={busy} onClick={settings.reload}>コマンドの一覧を再取得</button>}
    {!data ? !listError && <p role="status">コマンドの一覧を読み込み中です…</p>
      : <>
        <button type="button" className="btn btn--gray" hidden={editor !== null} disabled={busy || editor !== null}
          onClick={e => settings.open(null, e.currentTarget)}>コマンドを追加</button>
        {editor && <CommandEditor row={editor.row} parameterTypes={data.parameterTypes} settings={settings} />}
        {data.items.length === 0
          ? <p className="hint">追加のコマンドは未登録です。</p>
          : <ul className="settings-list">{data.items.map(row =>
            <SettingsListRow key={row.id} title={row.title} ariaLabel={`${row.title}、${diagnosticProductLabels[row.product]}`}
              preview={diagnosticProductLabels[row.product]}>
              <CommandDetails row={row} />
              <button type="button" className="btn btn--gray" disabled={busy || Boolean(editor)} onClick={e => settings.open(row, e.currentTarget)}>変更・削除</button>
            </SettingsListRow>,
          )}</ul>}
        {data.builtin.length > 0 && <details className="diagnostic-builtin">
          <summary>組み込みのコマンド（{data.builtin.length} 件）</summary>
          <ul className="settings-list">{data.builtin.map(row =>
            <SettingsListRow key={row.id} title={row.title} ariaLabel={`${row.title}、${diagnosticProductLabels[row.product]}`}
              preview={diagnosticProductLabels[row.product]}>
              <CommandDetails row={row} />
            </SettingsListRow>,
          )}</ul>
        </details>}
      </>}
  </section>
}
