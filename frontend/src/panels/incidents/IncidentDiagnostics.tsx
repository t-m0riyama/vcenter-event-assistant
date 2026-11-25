import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import {
  fetchDiagnosticCommands, fetchDiagnosticOutput, fetchDiagnosticProcedures, fetchIncidentProcedures, listDiagnosticTargets,
} from '../../api/diagnostics'
import type {
  DiagnosticCandidate, DiagnosticCommandInput, DiagnosticCommandRef, DiagnosticOutput, DiagnosticProcedure, DiagnosticRun,
} from '../../api/schemas/diagnostics'
import type { IncidentDetail } from '../../api/schemas/incidents'
import { toErrorMessage } from '../../utils/errors'
import { DiagnosticRunDialog } from './DiagnosticRunDialog'

type Selection = { command: DiagnosticCommandInput; reference: DiagnosticCommandRef; candidateTarget?: string; targets: Settings['targets']; triggerId: string }
type Settings = { catalog: Awaited<ReturnType<typeof fetchDiagnosticCommands>>; targets: Awaited<ReturnType<typeof listDiagnosticTargets>> }
const statusLabels = { succeeded: '成功', failed: '失敗', error: 'エラー' }
const statusBadges = { succeeded: 'badge--info', failed: 'badge--warning', error: 'badge--error' }

export function IncidentDiagnostics({ incident, active, canRun, writeBusy, format, refresh, onWrite, onMissing, onDialogOpenChange }: {
  incident: IncidentDetail
  active: boolean
  canRun: boolean
  writeBusy: boolean
  format: (iso: string) => string
  refresh: (signal: AbortSignal) => Promise<IncidentDetail>
  onWrite?: () => void
  onMissing: () => void
  onDialogOpenChange: (open: boolean) => void
}) {
  const [catalog, setCatalog] = useState<DiagnosticProcedure[] | null>(null)
  const [candidates, setCandidates] = useState<DiagnosticCandidate[] | null>(null)
  const [procedureError, setProcedureError] = useState<string | null>(null)
  const [settings, setSettings] = useState<Settings | null>(null)
  const [settingsError, setSettingsError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const opening = useRef<AbortController | null>(null)
  const [openingDialog, setOpeningDialog] = useState(false)
  const [selection, setSelection] = useState<Selection | null>(null)
  const [dialogVisible, setDialogVisible] = useState(false)
  const buttonPrefix = useId()
  const pendingFocus = useRef<string | null>(null)
  const reopenId = `${buttonPrefix}-reopen`

  useLayoutEffect(() => {
    if (!active || !canRun) pendingFocus.current = null
    if (pendingFocus.current === null) return
    const button = document.getElementById(pendingFocus.current)
    if (button instanceof HTMLButtonElement && !button.disabled) {
      pendingFocus.current = null
      button.focus()
    } else if (!button && candidates && settings && !openingDialog) {
      pendingFocus.current = null
    }
  })
  // 紐付けを増減したときにだけ候補を更新する。メモや診断の結果を保存しても候補は変わらない。
  const links = JSON.stringify([incident.events.map(({ id }) => id), incident.alerts.map(({ id }) => id)])
  const incidentId = incident.id

  useEffect(() => {
    if (!active) return
    const controller = new AbortController()
    void fetchDiagnosticProcedures(controller.signal).then(
      (data) => { if (!controller.signal.aborted) setCatalog(data) },
      (error: unknown) => { if (!controller.signal.aborted) setProcedureError(toErrorMessage(error)) },
    )
    return () => controller.abort()
  }, [active, retry])

  useEffect(() => {
    if (!active) return
    const controller = new AbortController()
    setCandidates(null)
    void fetchIncidentProcedures(incidentId, controller.signal).then(
      (data) => { if (!controller.signal.aborted) setCandidates(data) },
      (error: unknown) => { if (!controller.signal.aborted) setProcedureError(toErrorMessage(error)) },
    )
    return () => controller.abort()
  }, [active, incidentId, links, retry])

  useEffect(() => {
    if (!active || !canRun) return
    setSettingsError(null)
    const controller = new AbortController()
    void Promise.all([fetchDiagnosticCommands(controller.signal), listDiagnosticTargets(controller.signal)]).then(
      ([commands, targets]) => { if (!controller.signal.aborted) setSettings({ catalog: commands, targets }) },
      (error: unknown) => { if (!controller.signal.aborted) setSettingsError(toErrorMessage(error)) },
    )
    return () => controller.abort()
  }, [active, canRun, retry])

  useEffect(() => () => opening.current?.abort(), [active, canRun])

  const openDialog = async (reference: DiagnosticCommandRef, triggerId: string, candidateTarget?: string) => {
    if (opening.current || selection) return
    const controller = new AbortController()
    opening.current = controller
    setOpeningDialog(true)
    setSettingsError(null)
    try {
      const [commands, targets] = await Promise.all([fetchDiagnosticCommands(controller.signal), listDiagnosticTargets(controller.signal)])
      if (controller.signal.aborted) return
      setSettings({ catalog: commands, targets })
      const command = 'builtin' in reference
        ? commands.builtin.find(({ id }) => id === reference.builtin)
        : commands.items.find(({ id }) => id === reference.custom)
      if (!command) {
        setSettingsError('診断のコマンドが見つかりません。')
        return
      }
      onDialogOpenChange(true)
      setSelection({ command, reference, targets, candidateTarget, triggerId })
      setDialogVisible(true)
    } catch (error) {
      if (!controller.signal.aborted) setSettingsError(toErrorMessage(error))
    } finally {
      opening.current = null
      setOpeningDialog(false)
    }
  }

  const otherProcedures = catalog?.filter((item) => !candidates?.some(({ procedure }) => procedure.pattern_id === item.pattern_id))
  const procedureCommands = new Set([...(catalog ?? []), ...(candidates?.map(({ procedure }) => procedure) ?? [])]
    .flatMap(({ steps }) => steps.flatMap(({ commands }) => commands.map(({ id }) => id))))
  const otherBuiltinCommands = settings?.catalog.builtin.filter(({ id }) => !procedureCommands.has(id)) ?? []
  const renderProcedure = (procedure: DiagnosticProcedure, candidate?: DiagnosticCandidate) => (
    <ol className="incident-diagnostic-steps">
      {procedure.steps.map((step, index) => (
        <li key={index}>
          <p>{step.text}</p>
          {step.commands.map(({ id, title }) => {
            const command = settings?.catalog.builtin.find((item) => item.id === id)
            const triggerId = `${buttonPrefix}-${procedure.pattern_id}-${index}-${id}`
            return (
              <div key={id} className="incident-actions">
                <span>{title}</span>
                {canRun && (
                  <button id={triggerId} type="button" className="btn" aria-label={`${title}を実行`} disabled={!command || writeBusy || openingDialog || selection !== null}
                    onClick={() => void openDialog({ builtin: id }, triggerId, candidate?.target?.id)}>実行</button>
                )}
              </div>
            )
          })}
        </li>
      ))}
    </ol>
  )

  const renderCommands = (commands: (DiagnosticCommandInput & { id: string })[], kind: 'builtin' | 'custom') => (
    <ul className="incident-records">
      {commands.map((command) => (
        <li key={command.id}>
          <div className="incident-actions">
            <strong>{command.title}</strong>
            <span className="hint">{command.product === 'esxi' ? 'ESXi' : 'vCenter'}</span>
            <button id={`${buttonPrefix}-${kind}-${command.id}`} type="button" className="btn"
              aria-label={`${command.title}を実行`} disabled={writeBusy || openingDialog || selection !== null}
              onClick={() => void openDialog(
                kind === 'builtin' ? { builtin: command.id } : { custom: command.id }, `${buttonPrefix}-${kind}-${command.id}`,
              )}>実行</button>
          </div>
          {command.description && <p className="incident-text">{command.description}</p>}
        </li>
      ))}
    </ul>
  )

  return (
    <>
      <section>
        <h3>対応手順</h3>
        {procedureError && <p className="error-banner" role="alert">対応手順を読み込めませんでした。{procedureError}</p>}
        {canRun && (openingDialog || !settings) && !settingsError && <p className="hint" role="status">診断の設定を読み込み中…</p>}
        {canRun && settingsError && <p className="error-banner" role="alert">診断の設定を読み込めませんでした。{settingsError}</p>}
        {(procedureError || (canRun && settingsError)) && (
          <button type="button" className="btn" onClick={() => {
            setProcedureError(null)
            setSettingsError(null)
            setRetry((value) => value + 1)
          }}>対応手順を読み直す</button>
        )}
        {!candidates && !procedureError && <p className="hint" role="status">候補の手順を読み込み中…</p>}
        {candidates?.length === 0 && <p className="hint">候補の手順はありません。</p>}
        {candidates?.map((candidate) => (
          <div key={candidate.procedure.pattern_id} className="incident-diagnostic-card">
            <h4>{candidate.procedure.title}</h4>
            {candidate.reasons.length > 0 && (
              <p className="hint">候補になった理由{' '}
                {candidate.reasons.map(({ kind, link_id }, index) => {
                  const alert = kind === 'alert' ? incident.alerts.find(({ id }) => id === link_id) : undefined
                  const event = kind === 'event' ? incident.events.find(({ id }) => id === link_id) : undefined
                  const occurredAt = (alert ?? event)?.occurred_at
                  const label = alert?.rule_name || event?.event_type || (kind === 'alert' ? '紐付けた通知' : '紐付けたイベント')
                  return (
                    <span key={`${kind}-${link_id}`}>
                      {index > 0 && ' ・ '}
                      <button type="button" className="timeline-link incident-link-button--compact" onClick={() => {
                        const row = document.getElementById(`incident-${incidentId}-${kind}-${link_id}`)
                        row?.focus({ preventScroll: true })
                        row?.scrollIntoView({ block: 'nearest' })
                      }}>{label}{occurredAt && `（${format(occurredAt)}）`}</button>
                    </span>
                  )
                })}
              </p>
            )}
            {renderProcedure(candidate.procedure, candidate)}
          </div>
        ))}
        {candidates && otherProcedures && otherProcedures.length > 0 && (
          <details>
            <summary>ほかの手順</summary>
            {otherProcedures.map((procedure) => (
              <details key={procedure.pattern_id} className="incident-diagnostic-card">
                <summary>{procedure.title}</summary>
                {renderProcedure(procedure)}
              </details>
            ))}
          </details>
        )}
        {canRun && settings && (
          <details>
            <summary>ほかのコマンド</summary>
            {settings.catalog.items.length > 0 && (
              <>
                <h4>追加のコマンド</h4>
                {renderCommands(settings.catalog.items, 'custom')}
              </>
            )}
            {otherBuiltinCommands.length > 0 && (
              <details className="incident-diagnostic-card">
                <summary>手順にない組み込みのコマンド</summary>
                {renderCommands(otherBuiltinCommands, 'builtin')}
              </details>
            )}
            {settings.catalog.items.length === 0 && otherBuiltinCommands.length === 0 && <p className="hint">ほかのコマンドはありません。</p>}
          </details>
        )}
      </section>

      <section>
        <h3>診断の結果</h3>
        {canRun && selection && !dialogVisible && (
          <button id={reopenId} type="button" className="btn" onClick={() => setDialogVisible(true)}>診断の結果確認を開く</button>
        )}
        {incident.diagnostic_runs.length === 0 ? <p className="hint">診断の結果はありません。</p> : (
          <ul className="incident-records">
            {incident.diagnostic_runs.map((run) => <DiagnosticResult key={run.id} run={run} format={format} />)}
          </ul>
        )}
      </section>

      {selection && (
        <DiagnosticRunDialog
          incident={incident}
          active={active && dialogVisible}
          canRun={canRun}
          command={selection.command}
          reference={selection.reference}
          targets={selection.targets}
          candidateTarget={selection.candidateTarget}
          refresh={refresh}
          onWrite={onWrite}
          onMissing={onMissing}
          onHide={() => {
            pendingFocus.current = reopenId
            setDialogVisible(false)
          }}
          onClose={() => {
            // 隠したまま閉じたときは、利用者がほかで操作しているのでフォーカスを動かさない。
            pendingFocus.current = active && canRun && dialogVisible ? selection.triggerId : null
            setSelection(null)
            setDialogVisible(false)
            onDialogOpenChange(false)
          }}
        />
      )}
    </>
  )
}

const errorLabels: Record<string, string> = {
  invalid_command: 'コマンドか引数を確認できませんでした。',
  connect_failed: 'SSH 接続ができませんでした。',
  host_key_mismatch: 'ホスト鍵が承認済みの鍵と一致しません。',
  auth_failed: 'SSH の鍵で認証できませんでした。',
  shell_unavailable: 'vCenter で Bash を利用できませんでした。',
  no_exit_status: '終了コードを取得できませんでした。',
  timeout: '実行が時間切れになりました。',
  worker_unavailable: '診断ワーカーを利用できませんでした。',
}

function DiagnosticResult({ run, format }: { run: DiagnosticRun; format: (iso: string) => string }) {
  const [open, setOpen] = useState(false)
  const [output, setOutput] = useState<DiagnosticOutput | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || output || error) return
    const controller = new AbortController()
    void fetchDiagnosticOutput(run.incident_id, run.id, controller.signal).then(
      (data) => { if (!controller.signal.aborted) setOutput(data) },
      (err: unknown) => { if (!controller.signal.aborted) setError(toErrorMessage(err)) },
    )
    return () => controller.abort()
  }, [open, output, error, run.incident_id, run.id])

  return (
    <li>
      <details onToggle={(event) => setOpen(event.currentTarget.open)}>
        <summary>
          <strong>{run.command_title}</strong>{' ・ '}{run.host_name}{' ・ '}
          <span className={`badge ${statusBadges[run.status]}`}>{statusLabels[run.status]}</span>{' ・ '}
          終了コード {run.exit_status ?? '—'}{' ・ '}{run.run_by}{' ・ '}
          <time dateTime={run.started_at}>{format(run.started_at)}</time>
        </summary>
        <dl className="incident-fields">
          <div><dt>SSH 接続先</dt><dd>{run.ssh_host}（ポート {run.ssh_port}）</dd></div>
          <div><dt>SSH ユーザー名</dt><dd>{run.ssh_username}</dd></div>
          <div><dt>対象での実行</dt><dd>{run.executed === null ? '不明' : run.executed ? '実行を要求済み' : '実行なし'}</dd></div>
        </dl>
        {run.error_code && <p>{errorLabels[run.error_code] ?? '診断の実行中にエラーが発生しました。'}</p>}
        <pre className="incident-diagnostic-output">{run.command_line}</pre>
        {error && (
          <>
            <p className="error-banner" role="alert">出力を読み込めませんでした。{error}</p>
            <button type="button" className="btn" onClick={() => setError(null)}>出力を読み直す</button>
          </>
        )}
        {open && !error && !output && <p className="hint" role="status">出力を読み込み中…</p>}
        {output && (
          <>
            <h4>標準出力</h4>
            {output.stdout_truncated && <p className="hint">標準出力を切り詰めました。</p>}
            <pre className="incident-diagnostic-output">{output.stdout || '（出力なし）'}</pre>
            <h4>標準エラー</h4>
            {output.stderr_truncated && <p className="hint">標準エラーを切り詰めました。</p>}
            <pre className="incident-diagnostic-output">{output.stderr || '（出力なし）'}</pre>
          </>
        )}
      </details>
    </li>
  )
}
