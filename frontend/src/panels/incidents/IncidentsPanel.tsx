import { useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState, type Ref } from 'react'
import { ApiError } from '../../api'
import { getIncident, INCIDENT_PAGE_SIZE, listIncidents } from '../../api/incidents'
import type { IncidentDetail, IncidentList, IncidentStatus } from '../../api/schemas/incidents'
import { useAuth } from '../../auth/useAuth'
import { SeverityBadge } from '../../components/badges'
import { Pagination } from '../../components/Pagination'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { useTimeZone } from '../../datetime/useTimeZone'
import { incidentHash, incidentIdFromHash, replaceIncidentHash } from '../../routing/incidentHash'
import { parseAppHash } from '../../routing/appHashRouting'
import { toErrorMessage } from '../../utils/errors'
import { IncidentDetails, type IncidentDraftHandle } from './IncidentDetails'
import { keepEditedFields } from './incidentDetailRefresh'
import { IncidentLinkButton, IncidentLinkDialogProvider } from './IncidentLinkDialog'
import { INCIDENT_STATUS_BADGES, INCIDENT_STATUS_LABELS } from './incidentLabels'
import './IncidentsPanel.css'

type DetailExit = 'deleted' | 'missing'

const STATUSES = ['open', 'monitoring', 'resolved'] as const
type StatusFilter = IncidentStatus | 'unresolved' | 'all'

export type IncidentsPanelHandle = { showList: () => void }

export function IncidentsPanel({ active, canRunDiagnostics, ref, onOpenSnapshot }: {
  active: boolean
  canRunDiagnostics: boolean
  ref?: Ref<IncidentsPanelHandle>
  onOpenSnapshot: (id: string) => void
}) {
  const [id, setId] = useState(() => incidentIdFromHash(window.location.hash))
  // 履歴で表示する詳細が変わっても、診断のダイアログを開いている詳細は保持する。
  const [diagnosticIds, setDiagnosticIds] = useState<string[]>([])
  const detailIds = [...new Set([id, ...diagnosticIds])].filter((value) => value !== null)
  const [missing, setMissing] = useState(false)
  const draftRef = useRef<IncidentDraftHandle>(null)
  const [wasActive, setWasActive] = useState(active)
  if (wasActive !== active) {
    setWasActive(active)
    if (!active) setMissing(false)
  }

  useEffect(() => {
    const readHash = (event: HashChangeEvent) => {
      // 短時間に移動が続いたときは、現在の URL に対応する変更だけを反映する。
      if (event.newURL && event.newURL !== window.location.href) return
      if (parseAppHash(window.location.hash).tab !== 'incidents') {
        setMissing(false)
        return
      }
      const nextId = incidentIdFromHash(window.location.hash)
      setId(nextId)
      if (nextId !== null) setMissing(false)
    }
    window.addEventListener('hashchange', readHash)
    return () => window.removeEventListener('hashchange', readHash)
  }, [])

  useLayoutEffect(() => {
    if (active && parseAppHash(window.location.hash).tab === 'incidents') replaceIncidentHash(id)
  }, [active, id])

  const back = useCallback((exit?: DetailExit) => {
    if (!active || parseAppHash(window.location.hash).tab !== 'incidents') return
    if (id !== incidentIdFromHash(window.location.hash)) return
    if (!exit && draftRef.current?.hasDraft() && !window.confirm('保存していない入力を破棄して一覧に戻りますか？')) return
    setMissing(exit === 'missing')
    setId(null)
    if (exit) {
      setDiagnosticIds((current) => current.filter((detailId) => detailId !== id))
      replaceIncidentHash(null)
    } else window.location.hash = incidentHash(null)
  }, [active, id])

  useImperativeHandle(ref, () => ({ showList: () => back() }), [back])

  const open = (nextId: string) => {
    setMissing(false)
    setId(nextId)
    window.location.hash = incidentHash(nextId)
  }

  return (
    <section className="panel incidents-panel">
      {missing && <p className="error-banner" role="alert">インシデントが見つかりません</p>}
      <IncidentLinkDialogProvider active={active && id === null} hidden={id !== null}>
        <IncidentListView active={active && id === null} onOpen={open} onFilter={() => setMissing(false)} />
      </IncidentLinkDialogProvider>
      {detailIds.map((detailId) => (
        <div key={detailId} hidden={!active || detailId !== id}>
          <IncidentDetailView ref={detailId === id ? draftRef : null} id={detailId} active={active && detailId === id}
            canRunDiagnostics={canRunDiagnostics} onBack={back} onOpenSnapshot={onOpenSnapshot}
            onDiagnosticDialog={(open) => setDiagnosticIds((ids) =>
              open ? [...ids, detailId] : ids.filter((openedId) => openedId !== detailId)
            )} />
        </div>
      ))}
    </section>
  )
}

function IncidentListView({ active, onOpen, onFilter }: {
  active: boolean
  onOpen: (id: string) => void
  onFilter: () => void
}) {
  const { timeZone } = useTimeZone()
  const canWrite = useAuth().hasRole('operator')
  const [filter, setFilter] = useState<StatusFilter>('unresolved')
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const [offset, setOffset] = useState(0)
  const [reload, setReload] = useState(0)
  const [list, setList] = useState<IncidentList | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!active) return
    const controller = new AbortController()
    const statuses = filter === 'unresolved' ? undefined : filter === 'all' ? STATUSES : [filter]
    void listIncidents({ statuses, query, offset, signal: controller.signal }).then(
      (data) => {
        if (controller.signal.aborted) return
        if (!data.items.length && offset > 0) {
          setOffset(Math.max(0, Math.floor((data.total - 1) / INCIDENT_PAGE_SIZE) * INCIDENT_PAGE_SIZE))
        } else {
          setList(data)
          setError(null)
        }
      },
      (err: unknown) => { if (!controller.signal.aborted) setError(toErrorMessage(err)) },
    )
    return () => controller.abort()
  }, [active, filter, query, offset, reload])

  const changePage = (next: number) => {
    setList(null)
    setError(null)
    setOffset(next)
  }

  return (
    <>
      <h2>インシデント</h2>
      <form className="toolbar" onSubmit={(event) => {
        event.preventDefault()
        onFilter()
        const next = draft.trim()
        if (query !== next || offset !== 0) changePage(0)
        setQuery(next)
      }}>
        <label>状態
          <select value={filter} onChange={(event) => {
            onFilter()
            changePage(0)
            setFilter(event.target.value as StatusFilter)
          }}>
            <option value="unresolved">未解決</option>
            {STATUSES.map((status) => <option key={status} value={status}>{INCIDENT_STATUS_LABELS[status]}</option>)}
            <option value="all">すべて</option>
          </select>
        </label>
        <label>件名
          <input type="search" value={draft} onChange={(event) => setDraft(event.target.value)} />
        </label>
        <button type="submit" className="btn">検索</button>
        {canWrite && (
          <IncidentLinkButton createOnly onCreated={(nextId, openDetails) => {
            if (openDetails && window.location.hash === incidentHash(null)) {
              onOpen(nextId)
              return true
            }
            setReload((previous) => previous + 1)
            return false
          }} />
        )}
      </form>
      {error && <p className="error-banner" role="alert">{error}</p>}
      {list ? (
        list.items.length ? (
          <>
            <div className="table-container table-scroll">
              <table className="table">
                <thead><tr>
                  <th>件名</th><th>状態</th><th>重大度</th><th>担当</th><th>開始時刻</th><th>最終更新</th><th>紐付け</th>
                </tr></thead>
                <tbody>{list.items.map((item) => (
                  <tr key={item.id}>
                    <td><a className="incident-list-title" href={incidentHash(item.id)} onClick={(event) => {
                      if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
                      event.preventDefault()
                      onOpen(item.id)
                    }}>{item.title}</a></td>
                    <td><span className={INCIDENT_STATUS_BADGES[item.status]}>{INCIDENT_STATUS_LABELS[item.status]}</span></td>
                    <td><SeverityBadge severity={item.level} /></td>
                    <td>{item.assignee || '—'}</td>
                    <td>{item.started_at ? formatIsoInTimeZone(item.started_at, timeZone) : '—'}</td>
                    <td>{formatIsoInTimeZone(item.updated_at, timeZone)}</td>
                    <td>イベント {item.event_count} / 通知 {item.alert_count} / スナップショット {item.snapshot_count}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
            <Pagination position="bottom" total={list.total} start={offset + 1} end={offset + list.items.length}
              canPrev={offset > 0} canNext={offset + INCIDENT_PAGE_SIZE < list.total}
              onPrev={() => changePage(offset - INCIDENT_PAGE_SIZE)} onNext={() => changePage(offset + INCIDENT_PAGE_SIZE)} />
          </>
        ) : <p className="table-empty">条件に一致するインシデントはありません</p>
      ) : !error && <p className="hint" role="status">読み込み中…</p>}
    </>
  )
}

function IncidentDetailView({ ref, id, active, canRunDiagnostics, onBack, onOpenSnapshot, onDiagnosticDialog }: {
  ref: Ref<IncidentDraftHandle>
  id: string
  active: boolean
  canRunDiagnostics: boolean
  onBack: (exit?: DetailExit) => void
  onOpenSnapshot: (id: string) => void
  onDiagnosticDialog: (open: boolean) => void
}) {
  const [detail, setDetail] = useState<IncidentDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [exit, setExit] = useState<DetailExit | null>(null)
  const draftRef = useRef<IncidentDraftHandle>(null)
  /** 書き込みの始めと終わりに進める。タブに戻ったときの読み直しは、始めたときと違えば応答を捨てる。 */
  const writeGeneration = useRef(0)
  const wasActive = useRef(active)
  const hasDetail = detail !== null
  useImperativeHandle(ref, () => ({ hasDraft: () => draftRef.current?.hasDraft() ?? false }), [])

  // 詳細はタブを離れても残すので、ほかのタブで紐付けを足しても古いままになる。タブに戻ったら読み直す。
  useEffect(() => {
    const returned = active && !wasActive.current
    wasActive.current = active
    if (!returned || !hasDetail) return
    const controller = new AbortController()
    const generation = writeGeneration.current
    void getIncident(id, controller.signal).then(
      (data) => {
        // 読み直しのあいだに保存・メモ・解除が始まったか終わったなら、この応答は書き込みより古いかもしれないので捨てる。
        if (controller.signal.aborted || writeGeneration.current !== generation) return
        setDetail((current) => current && draftRef.current?.hasDraft() ? keepEditedFields(current, data) : data)
      },
      (err: unknown) => {
        if (controller.signal.aborted || writeGeneration.current !== generation) return
        if (err instanceof ApiError && err.status === 404) setExit('missing')
        // そのほかの失敗では、表示中の内容をそのまま残す。
      },
    )
    return () => controller.abort()
  }, [active, hasDetail, id])

  useEffect(() => {
    if (!active || detail || error || exit) return
    const controller = new AbortController()
    void getIncident(id, controller.signal).then(
      (data) => { if (!controller.signal.aborted) setDetail(data) },
      (err: unknown) => {
        if (controller.signal.aborted) return
        if (err instanceof ApiError && err.status === 404) setExit('missing')
        else setError(toErrorMessage(err))
      },
    )
    return () => controller.abort()
  }, [active, detail, error, exit, id])

  useEffect(() => {
    if (active && exit) onBack(exit)
  }, [active, exit, onBack])

  return (
    <>
      <button type="button" className="btn" onClick={() => onBack()}>一覧に戻る</button>
      {detail ? (
        <IncidentDetails
          ref={draftRef}
          incident={detail}
          active={active}
          canRunDiagnostics={canRunDiagnostics}
          onDiagnosticDialog={onDiagnosticDialog}
          onChange={setDetail}
          onWrite={() => { writeGeneration.current += 1 }}
          onDeleted={() => setExit('deleted')}
          onMissing={() => setExit('missing')}
          onOpenSnapshot={onOpenSnapshot}
        />
      ) : error ? (
        <>
          <p className="error-banner" role="alert">{error}</p>
          <button type="button" className="btn" onClick={() => setError(null)}>読み直す</button>
        </>
      ) : <p className="hint" role="status">読み込み中…</p>}
    </>
  )
}
