import { useEffect, useEffectEvent, useId, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { createPortal } from 'react-dom'
import { ApiError } from '../../api'
import { executeDiagnosticRun, previewDiagnosticRun } from '../../api/diagnostics'
import {
  diagnosticParameterErrorsSchema, type DiagnosticCommandInput, type DiagnosticCommandRef, type DiagnosticPreview,
  type DiagnosticPreviewInput, type DiagnosticRun, type DiagnosticTarget,
} from '../../api/schemas/diagnostics'
import type { IncidentDetail } from '../../api/schemas/incidents'
import { toErrorMessage } from '../../utils/errors'
import { useAuth } from '../../auth/useAuth'
import { incidentActorName } from './incidentLabels'

const runErrorLabels: Record<string, string> = {
  diagnostic_busy: '診断の実行枠に空きがありません。時間をおいて実行してください。',
  incident_diagnostic_limit: 'このインシデントに保存できる診断の結果は 100 件までです。',
  diagnostic_host_key_unapproved: '設定の「診断」で接続先のホスト鍵を承認してください。',
  diagnostic_template_invalid: '設定の「診断」でコマンドの雛形を確認してください。',
  diagnostic_params_invalid: '引数を確認してください。',
  diagnostic_port_not_allowed: '接続先の SSH ポートが許可されていません。',
  diagnostic_product_mismatch: 'コマンドと対象の製品が一致していません。',
  diagnostic_target_not_found: '診断の対象が見つかりません。設定の「診断」で対象を確認してください。',
  diagnostic_command_not_found: '診断のコマンドが見つかりません。設定の「診断」でコマンドを確認してください。',
  diagnostic_connection_not_found: '診断用の SSH 接続先が見つかりません。設定の「診断」で接続先を確認してください。',
  diagnostic_credential_not_found: '診断用の SSH 鍵が見つかりません。設定の「診断」で鍵を確認してください。',
  incident_not_found: 'インシデントが見つかりません。',
  diagnostic_internal_error: '診断の処理中にエラーが発生しました。実行の状態は監査ログで確認できます。',
  diagnostic_save_failed: '診断の結果を保存できませんでした。実行の状態は監査ログで確認してください。',
}
const parameterErrorLabels = { missing: '値を入力してください。', unknown: '定義にない引数です。', invalid_value: '値の形式を確認してください。' }
const reviewResultCodes = new Set([
  'diagnostic_internal_error', 'diagnostic_save_failed', 'incident_diagnostic_limit', 'incident_not_found',
])
const executionTimeout = 70_000
// 応答が途切れた後も、サーバーでの準備、実行と保存を待つ。
const recoveryWindow = 65_000
const recoveryInterval = 5_000
// サーバーとブラウザの時計のずれを見込む幅。同じ接続先は同時に 1 本しか走らないので、
// 数分さかのぼっても別の実行と取り違えることはほとんどない。
const clockSkewAllowance = 5 * 60_000

/** `AbortSignal.any` が無いブラウザでも、どれかが中止されたら中止されるシグナルを返す。 */
function anySignal(signals: AbortSignal[]): AbortSignal {
  if (typeof AbortSignal.any === 'function') return AbortSignal.any(signals)
  const controller = new AbortController()
  for (const item of signals) {
    if (item.aborted) {
      controller.abort(item.reason)
      break
    }
    item.addEventListener('abort', () => controller.abort(item.reason), { once: true })
  }
  return controller.signal
}

/** `AbortSignal.timeout` が無いブラウザでも、`ms` 後に中止されるシグナルを返す。 */
function timeoutSignal(ms: number): AbortSignal {
  if (typeof AbortSignal.timeout === 'function') return AbortSignal.timeout(ms)
  const controller = new AbortController()
  setTimeout(() => controller.abort(new DOMException('signal timed out', 'TimeoutError')), ms)
  return controller.signal
}

function describesUncertainRun(error: unknown) {
  return !(error instanceof ApiError) || (error.status >= 500 && error.errorCode === null)
}

function errorMessage(error: unknown) {
  if (error instanceof ApiError && error.status === 429) {
    return '短い間に実行が多すぎます。しばらく待ってから実行してください。'
  }
  return (error instanceof ApiError && error.errorCode && runErrorLabels[error.errorCode]) || toErrorMessage(error)
}

function waitForRefresh(delay: number, signal: AbortSignal) {
  return new Promise<void>((resolve) => {
    if (signal.aborted) {
      resolve()
      return
    }
    const finish = () => {
      clearTimeout(timer)
      signal.removeEventListener('abort', finish)
      resolve()
    }
    const timer = setTimeout(finish, delay)
    signal.addEventListener('abort', finish, { once: true })
  })
}

export function DiagnosticRunDialog({ incident, active, canRun, command, reference, targets, candidateTarget, refresh, onWrite, onMissing, onHide, onClose }: {
  incident: IncidentDetail
  active: boolean
  canRun: boolean
  command: DiagnosticCommandInput
  reference: DiagnosticCommandRef
  targets: DiagnosticTarget[]
  candidateTarget?: string
  refresh: (signal: AbortSignal) => Promise<IncidentDetail>
  onWrite?: () => void
  onMissing: () => void
  onHide: () => void
  onClose: () => void
}) {
  const heading = useId()
  const { me } = useAuth()
  const dialog = useRef<HTMLDialogElement>(null)
  const lifecycle = useRef<AbortController | null>(null)
  const running = useRef(false)
  const submitted = useRef(false)
  const matchesRecovery = useRef<((run: DiagnosticRun) => boolean) | null>(null)
  const compatible = targets.filter((target) => target.product === command.product)
  const [input, setInput] = useState<DiagnosticPreviewInput>(() => ({
    target_id: compatible.find(({ id }) => id === candidateTarget)?.id ?? '',
    command: reference,
    params: {},
  }))
  const [request, setRequest] = useState<{ input: DiagnosticPreviewInput; delay: number } | null>(null)
  const [preview, setPreview] = useState<{ input: DiagnosticPreviewInput; data: DiagnosticPreview } | null>(null)
  const [previewError, setPreviewError] = useState<unknown>(null)
  const [runError, setRunError] = useState<unknown>(null)
  const [checking, setChecking] = useState(false)
  const [phase, setPhase] = useState<'ready' | 'running' | 'refreshing' | 'done'>('ready')
  const [notice, setNotice] = useState<string | null>(null)
  const [refreshError, setRefreshError] = useState(false)
  const [manualRefresh, setManualRefresh] = useState(false)
  const reviewed = preview?.input === input ? preview.data : null
  const sending = phase === 'running'
  const canHideRunning = phase === 'refreshing' || manualRefresh
  const busy = sending || canHideRunning
  const uncertainResponse = runError != null && describesUncertainRun(runError)
  const lastError = previewError ?? runError
  const fieldErrors = lastError instanceof ApiError && lastError.status === 422 && lastError.errorCode === 'diagnostic_params_invalid'
    ? diagnosticParameterErrorsSchema.safeParse(lastError.detail).data ?? []
    : []
  const incidentId = incident.id

  // 履歴の移動で表示だけを外す。送信済みなら応答と読み直しを保持する。
  const closeIfIdle = useEffectEvent(() => {
    if (!busy && (!canRun || !submitted.current)) onClose()
  })
  useLayoutEffect(() => {
    if (!active || !canRun) closeIfIdle()
    else if (dialog.current && !dialog.current.open) dialog.current.showModal()
  }, [active, canRun, busy])

  useEffect(() => {
    const controller = new AbortController()
    lifecycle.current = controller
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!request?.input.target_id) return
    let current = true
    const timer = setTimeout(() => {
      void previewDiagnosticRun(incidentId, request.input).then(
        (data) => { if (current) setPreview({ input: request.input, data }) },
        (error: unknown) => { if (current) setPreviewError(error) },
      ).finally(() => { if (current) setChecking(false) })
    }, request.delay)
    return () => {
      current = false
      clearTimeout(timer)
    }
  }, [incidentId, request])

  const requestPreview = (values: DiagnosticPreviewInput, delay = 0) => {
    setPreview(null)
    setPreviewError(null)
    setChecking(Boolean(values.target_id))
    setRequest({ input: values, delay })
  }

  const edit = (values: DiagnosticPreviewInput) => {
    setInput(values)
    setRunError(null)
    setNotice(null)
    if (request) requestPreview(values, 250)
  }

  const readResult = async (signal: AbortSignal) => {
    try {
      const latest = await refresh(signal)
      if (signal.aborted) return null
      setRefreshError(false)
      const matches = matchesRecovery.current
      if (matches && latest.diagnostic_runs.some(matches)) {
        matchesRecovery.current = null
        setRunError(null)
        setNotice('保存された結果が見つかりました。')
      }
      return latest
    } catch (error) {
      if (signal.aborted) return null
      if (error instanceof ApiError && error.status === 404) {
        onMissing()
        return null
      }
      setRefreshError(true)
      return undefined
    }
  }

  const readAgain = async () => {
    const signal = lifecycle.current?.signal
    if (!signal || running.current) return
    running.current = true
    setManualRefresh(true)
    onWrite?.()
    try {
      await readResult(signal)
    } finally {
      onWrite?.()
      running.current = false
      if (!signal.aborted) setManualRefresh(false)
    }
  }

  const close = () => {
    if (running.current && !canHideRunning) return
    dialog.current?.close()
    if (running.current) onHide()
    else onClose()
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const signal = lifecycle.current?.signal
    if (running.current || !reviewed || !signal || phase !== 'ready') return
    running.current = true
    submitted.current = true
    setPhase('running')
    setRunError(null)
    setNotice(null)
    setRefreshError(false)
    onWrite?.()
    const submittedAt = Date.now()
    let uncertain = false
    let completed = false
    try {
      const requestSignal = anySignal([signal, timeoutSignal(executionTimeout)])
      const result = await executeDiagnosticRun(incidentId, input, reviewed.fingerprint, requestSignal)
      completed = true
      setNotice(result.status === 'succeeded' ? '診断の結果に保存しました。' : '診断が失敗しました。診断の結果で詳細を確認できます。')
    } catch (error) {
      const changed = error instanceof ApiError && error.status === 409 && error.errorCode === 'diagnostic_changed'
      uncertain = describesUncertainRun(error)
      if (changed) {
        setNotice('診断の設定が変わりました。新しいプレビューを確認してください。')
        requestPreview(input)
      } else {
        setPreview(null)
        setRequest(null)
        setRunError(error)
        if (error instanceof ApiError && error.errorCode && reviewResultCodes.has(error.errorCode)) {
          setNotice('結果を確かめてから、必要ならプレビューを取り直して実行してください。')
        }
      }
    }

    if (!signal.aborted) setPhase('refreshing')
    const recovery = uncertain ? new AbortController() : null
    const timer = recovery && setTimeout(() => recovery.abort(), recoveryWindow)
    try {
      if (uncertain) {
        const previousIds = new Set(incident.diagnostic_runs.map(({ id }) => id))
        const kind = 'builtin' in reference ? 'builtin' : 'custom'
        const ref = 'builtin' in reference ? reference.builtin : reference.custom
        const actor = incidentActorName(me)
        matchesRecovery.current = (run) =>
          !previousIds.has(run.id) && Date.parse(run.started_at) >= submittedAt - clockSkewAllowance && run.target_id === input.target_id &&
          run.command_kind === kind && run.command_ref === ref && run.command_line === reviewed.command_line &&
          run.ssh_host === reviewed.ssh_host && run.ssh_port === reviewed.ssh_port &&
          run.ssh_username === reviewed.ssh_username && run.run_by === actor
      }
      const readSignal = recovery ? anySignal([signal, recovery.signal]) : signal
      while (!readSignal.aborted) {
        const latest = await readResult(readSignal)
        if (latest === null || !matchesRecovery.current) break
        await waitForRefresh(recoveryInterval, readSignal)
      }
    } finally {
      if (timer !== null) clearTimeout(timer)
      onWrite?.()
      running.current = false
      submitted.current = completed || uncertain
      if (!signal.aborted) setPhase(completed || uncertain ? 'done' : 'ready')
    }
  }

  if (!active || !canRun) return null
  return createPortal(
    <dialog ref={dialog} className="dialog incident-dialog incident-diagnostic-dialog" aria-labelledby={heading}
      onClose={(event) => {
        if (event.currentTarget.open) return
        // 取り消せない Esc で閉じた場合も、同じ操作の表示を戻す。
        if (running.current && !canHideRunning) event.currentTarget.showModal()
        else if (running.current) onHide()
        else onClose()
      }} onCancel={(event) => { if (running.current && !canHideRunning) event.preventDefault() }}>
      <form onSubmit={(event) => void submit(event)}>
        <header className="dialog__header">
          <h2 id={heading} className="dialog__title">{command.title}</h2>
        </header>
        <div className="dialog__body incident-dialog__fields">
          <p className="hint">診断用の鍵で、対象に強い権限のコマンドを送ります。追加のコマンドが読み取り専用かどうかは、本体では確かめません。実行は監査ログに記録されます。</p>
          <details>
            <summary>診断の権限と安全の詳細</summary>
            <p className="hint">診断は既定で無効です。有効化にはサーバーの設定と認証が必要です。設定と実行は admin に限られ、監査ログに記録されます。</p>
            <p className="hint">診断にはログ収集と別のアカウントと鍵を使います。組み込みのコマンドも強い権限で実行します。許可リストやワーカーの分離だけでは、侵害されたアプリやプラグインから鍵を守れません。</p>
            <p className="hint">鍵はワーカー内でファイルに保存せず、Linux では鍵を渡す前にワーカーのメモリの読み取りを制限します。診断の結果と経過はインシデントの閲覧者が読めます。</p>
          </details>
          <label>対象
            <select value={input.target_id} disabled={busy || phase === 'done'} onChange={(event) => edit({ ...input, target_id: event.target.value })}>
              <option value="">{compatible.length ? '選択してください' : 'この製品の対象が登録されていません'}</option>
              {compatible.map((target) => <option key={target.id} value={target.id}>{target.host_name}</option>)}
            </select>
          </label>
          {command.param_definitions.map(({ name, type }, index) => {
            const error = fieldErrors.find((item) => item.parameter === name)
            const errorId = `${heading}-param-${index}`
            return (
              <div key={name}>
                <label>{name}{name !== type && `（${type}）`}
                  <input value={Object.hasOwn(input.params, name) ? input.params[name] : ''} disabled={busy || phase === 'done'} aria-invalid={Boolean(error)}
                    aria-describedby={error ? errorId : undefined}
                    onChange={(event) => edit({ ...input, params: { ...input.params, [name]: event.target.value } })} />
                </label>
                {error && <p className="incident-diagnostic-field-error" id={errorId}>{parameterErrorLabels[error.reason]}</p>}
              </div>
            )
          })}
          {checking && <p role="status" className="hint">プレビューを取得中…</p>}
          {notice && <p role="status">{notice}</p>}
          {lastError != null && <p className="error-banner" role="alert">
            {uncertainResponse
              ? '実行の応答を受け取れませんでした。保存された結果を診断の結果で確認してください。'
              : errorMessage(lastError)}
            {fieldErrors.filter(({ parameter }) => !command.param_definitions.some(({ name }) => name === parameter))
              .map(({ parameter, reason }) => ` ${parameter}（${parameterErrorLabels[reason]}）`)}
          </p>}
          {refreshError && <p className="error-banner" role="alert">詳細を読み直せませんでした。</p>}
          {reviewed && (
            <>
              <p className="hint">対象と SSH 接続先が同じ機器を指すことを確認してください。</p>
              <dl className="incident-fields">
                <div><dt>対象のホスト名</dt><dd>{reviewed.host_name}</dd></div>
                <div><dt>SSH 接続先</dt><dd>{reviewed.ssh_host}（ポート {reviewed.ssh_port}）</dd></div>
                <div><dt>SSH ユーザー名</dt><dd>{reviewed.ssh_username}</dd></div>
              </dl>
              <div>送るコマンド<pre className="incident-diagnostic-output">{reviewed.command_line}</pre></div>
            </>
          )}
          {phase === 'running' && <p role="status">実行中… 結果の保存まで最大でおよそ 55 秒かかります。</p>}
          {(phase === 'refreshing' || manualRefresh) && <p role="status">最新の診断の結果を確認中…</p>}
        </div>
        <footer className="dialog__footer">
          {phase !== 'done' && !(phase === 'refreshing' && uncertainResponse) && (
            <>
              <button type="button" className="btn" disabled={!input.target_id || checking || busy}
                onClick={() => { setRunError(null); requestPreview(input) }}>プレビュー</button>
              <button type="submit" className="btn btn--filled" disabled={!reviewed || busy}>確認して実行</button>
            </>
          )}
          {phase !== 'refreshing' && (refreshError || uncertainResponse) && (
            <button type="button" className="btn" disabled={busy} onClick={() => void readAgain()}>結果を読み直す</button>
          )}
          <button type="button" className="btn" disabled={sending} onClick={close}>閉じる</button>
        </footer>
      </form>
    </dialog>,
    document.body,
  )
}
