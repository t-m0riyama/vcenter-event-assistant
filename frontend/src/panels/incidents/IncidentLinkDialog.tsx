import { createContext, useContext, useEffect, useEffectEvent, useId, useLayoutEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { addIncidentLinks, createIncident, INCIDENT_PAGE_SIZE, listIncidents, type IncidentLinkSource } from '../../api/incidents'
import type { IncidentList } from '../../api/schemas/incidents'
import { incidentHash } from '../../routing/incidentHash'
import { Pagination } from '../../components/Pagination'
import { toErrorMessage } from '../../utils/errors'
import { formatIncidentLinkResults } from './incidentLinkResults'
import './IncidentsPanel.css'

type LinkSelection = {
  source?: IncidentLinkSource
  notice?: string
  draftTitle?: string
  createOnly?: boolean
  /** 詳細に移った場合は true を返し、ダイアログの結果表示を省く。 */
  onCreated?: (id: string, openDetails: boolean) => boolean
}

const IncidentLinkContext = createContext<((selection: LinkSelection) => void) | null>(null)

/** 行が再取得で消えても、開いた画面と送信結果はパネルに残す。 */
export function IncidentLinkDialogProvider({ active, className, hidden, children }: {
  active: boolean
  className?: string
  hidden?: boolean
  children: ReactNode
}) {
  const [selection, setSelection] = useState<LinkSelection | null>(null)
  return (
    <IncidentLinkContext.Provider value={setSelection}>
      <div className={className} hidden={hidden}>{children}</div>
      {selection && <IncidentLinkDialog {...selection} active={active} onClose={() => setSelection(null)} />}
    </IncidentLinkContext.Provider>
  )
}

export function IncidentLinkButton({ compact = false, ...selection }: LinkSelection & { compact?: boolean }) {
  const open = useContext(IncidentLinkContext)
  if (!open) return null
  const className = selection.createOnly && !selection.source
    ? 'btn btn--filled'
    : compact ? 'timeline-link incident-link-button--compact' : 'btn btn--gray incident-link-button'
  return (
    <button
      type="button"
      className={className}
      onClick={() => open(selection)}
    >
      {selection.createOnly ? 'インシデントを作る' : 'インシデントに追加'}
    </button>
  )
}

function IncidentLinkDialog({
  active, source, notice, draftTitle = '', createOnly = false, onClose, onCreated,
}: LinkSelection & { active: boolean; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const mounted = useRef(false)
  const wasHidden = useRef(false)
  const headingId = useId()
  const [create, setCreate] = useState(createOnly)
  const [title, setTitle] = useState(draftTitle)
  const [selectedId, setSelectedId] = useState('')
  const [offset, setOffset] = useState(0)
  const [list, setList] = useState<IncidentList | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<{ id: string; message: string } | null>(null)

  useLayoutEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])

  // 非表示にした時点で送信中の操作だけを保持し、戻ったときに結果を出す。
  const closeIfIdle = useEffectEvent(() => { if (!busy) onClose() })
  useLayoutEffect(() => {
    if (!active) {
      wasHidden.current = true
      closeIfIdle()
    } else if (dialog.current && !dialog.current.open) {
      dialog.current.showModal()
    }
  }, [active])

  useEffect(() => {
    if (!active || create || done) return
    const controller = new AbortController()
    void listIncidents({ offset, signal: controller.signal }).then(
      (data) => { if (!controller.signal.aborted) setList(data) },
      (err: unknown) => { if (!controller.signal.aborted) setListError(toErrorMessage(err)) },
    )
    return () => controller.abort()
  }, [active, create, done, offset])

  const go = (next: number) => {
    setList(null)
    setListError(null)
    setSelectedId('')
    setOffset(next)
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy || done || (create ? !title.trim() : !selectedId || !source)) return
    setBusy(true)
    setError(null)
    try {
      if (create) {
        const links = source?.kind === 'snapshots' ? { snapshot_ids: source.ids }
          : source ? { [source.kind]: source.items } : {}
        const { incident, link_results } = await createIncident({ title, ...links })
        if (!mounted.current) return
        if (onCreated?.(incident.id, !wasHidden.current)) {
          onClose()
          return
        }
        const results = [...link_results.events, ...link_results.alerts, ...link_results.snapshots]
        const message = source
          ? `インシデントを作成しました。${formatIncidentLinkResults(results)}`
          : 'インシデントを作成しました。'
        setDone({ id: incident.id, message })
      } else if (source) {
        const { results } = await addIncidentLinks(selectedId, source)
        if (!mounted.current) return
        setDone({ id: selectedId, message: formatIncidentLinkResults(results) })
      }
    } catch (err) {
      if (mounted.current) setError(toErrorMessage(err))
    } finally {
      if (mounted.current) setBusy(false)
    }
  }

  return active ? createPortal(
    <dialog
      ref={dialog}
      className="dialog incident-dialog"
      aria-labelledby={headingId}
      onClose={onClose}
      onCancel={(event) => { if (busy) event.preventDefault() }}
    >
      <form onSubmit={(event) => void submit(event)}>
        <header className="dialog__header">
          <h2 id={headingId} className="dialog__title">{createOnly ? 'インシデントを作る' : 'インシデントに追加'}</h2>
        </header>
        <div className="dialog__body incident-dialog__fields">
          {done ? (
            <>
              <p role="status">{done.message}</p>
              <a className="timeline-link" href={incidentHash(done.id)} onClick={onClose}>インシデントを開く</a>
            </>
          ) : (
            <>
              {notice && <p className="hint">{notice}</p>}
              {!createOnly && (
                <label>追加先
                  <select value={create ? 'new' : 'existing'} disabled={busy} onChange={(event) => {
                    setError(null)
                    setCreate(event.target.value === 'new')
                  }}>
                    <option value="existing">未解決のインシデント</option>
                    <option value="new">新しく作る</option>
                  </select>
                </label>
              )}
              {create ? (
                <label>件名
                  <input required maxLength={200} value={title} disabled={busy} onChange={(event) => setTitle(event.target.value)} />
                </label>
              ) : list ? (
                <>
                  <label>未解決のインシデント
                    <select required value={selectedId} disabled={busy || list.items.length === 0} onChange={(event) => setSelectedId(event.target.value)}>
                      <option value="">{list.total === 0 ? '未解決のインシデントはありません' : '選択してください'}</option>
                      {list.items.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
                    </select>
                  </label>
                  {list.total > INCIDENT_PAGE_SIZE && (
                    <Pagination position="top" total={list.total} start={offset + 1} end={offset + list.items.length}
                      canPrev={offset > 0} canNext={offset + INCIDENT_PAGE_SIZE < list.total}
                      onPrev={() => go(offset - INCIDENT_PAGE_SIZE)} onNext={() => go(offset + INCIDENT_PAGE_SIZE)} loading={busy} />
                  )}
                </>
              ) : listError ? <p className="error-banner" role="alert">{listError}</p> : <p className="hint">読み込み中…</p>}
              {error && <p className="error-banner" role="alert">{error}</p>}
            </>
          )}
        </div>
        <footer className="dialog__footer">
          <button type="button" className="btn" disabled={busy} onClick={() => dialog.current?.close()}>{done ? '閉じる' : 'キャンセル'}</button>
          {!done && (
            <button type="submit" className="btn btn--filled" disabled={busy || (create ? !title.trim() : !list || !selectedId)}>
              {create ? '作成' : '追加'}
            </button>
          )}
        </footer>
      </form>
    </dialog>,
    document.body,
  ) : null
}
