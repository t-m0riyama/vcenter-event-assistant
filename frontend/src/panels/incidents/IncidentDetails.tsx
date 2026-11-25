import { useImperativeHandle, useRef, useState, type FormEvent, type ReactNode, type Ref } from 'react'
import { ApiError } from '../../api'
import { addIncidentEntry, deleteIncident, getIncident, patchIncident } from '../../api/incidents'
import { incidentLevelSchema, type IncidentDetail, type IncidentLevel, type IncidentPatch, type IncidentStatus } from '../../api/schemas/incidents'
import { alertStateLabel } from '../../alerts/alertStateLabel'
import { useAuth } from '../../auth/useAuth'
import { ScoreBadge, SeverityBadge } from '../../components/badges'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { useTimeZone } from '../../datetime/useTimeZone'
import { utcIsoToZonedLocalDateTimeInput, zonedLocalDateTimeToUtcIso } from '../../datetime/zonedLocalDateTime'
import { timelineEntryHash } from '../../routing/timelineHash'
import { toErrorMessage } from '../../utils/errors'
import { TimelineExportControls } from '../timeline/TimelineExportControls'
import { useTimelineExportActivity } from '../timeline/useTimelineExportActivity'
import { INCIDENT_STATUS_BADGES, INCIDENT_STATUS_LABELS } from './incidentLabels'
import { keepEditedFields } from './incidentDetailRefresh'

const STALE_MESSAGE = 'ほかの人が更新しました。読み直してください'
const ENTRY_KIND_LABELS: Record<IncidentDetail['entries'][number]['kind'], string> = {
  note: 'メモ',
  change: '項目の変更',
  link: '紐付けの変更',
}

const ENTRY_LIMIT_MESSAGE = 'メモが上限に達しました。新しいインシデントを作ってください'

export type IncidentDraftHandle = { hasDraft: () => boolean }

export function IncidentDetails({ ref, incident, onChange, onDeleted, onMissing, onOpenSnapshot, onWrite }: {
  ref?: Ref<IncidentDraftHandle>
  incident: IncidentDetail
  onChange: (detail: IncidentDetail) => void
  /** 書き込みの始めと終わりに呼ぶ。親は、これより前に始めた読み直しの応答を捨てる。 */
  onWrite?: () => void
  onDeleted: () => void
  onMissing: () => void
  onOpenSnapshot: (id: string) => void
}) {
  const { hasRole } = useAuth()
  const canWrite = hasRole('operator')
  const canDelete = hasRole('admin')
  const { timeZone } = useTimeZone()
  const format = (iso: string) => formatIsoInTimeZone(iso, timeZone)
  const [editing, setEditing] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [stale, setStale] = useState(false)
  const [showLatest, setShowLatest] = useState(false)
  const exportActivity = useTimelineExportActivity()
  const editorRef = useRef<IncidentDraftHandle>(null)
  useImperativeHandle(ref, () => ({
    hasDraft: () => note.trim() !== '' || (editorRef.current?.hasDraft() ?? false),
  }), [note])

  /**
   * 詳細を読み直す。編集の下書きがあるときは、紐付けと経過だけを最新にする（keepEditedFields）。
   * 409 のあとに利用者が押す「読み直す」だけは `full` で全部を最新にし、下書きと見比べられるようにする。
   */
  const reload = async (full = false) => {
    const fresh = await getIncident(incident.id)
    onChange(!full && editorRef.current?.hasDraft() ? keepEditedFields(incident, fresh) : fresh)
  }
  const run = async (action: () => Promise<void>) => {
    if (busy) return
    setBusy(true)
    setError(null)
    setFeedback(null)
    onWrite?.()
    try {
      await action()
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        onMissing()
      } else if (err instanceof ApiError && err.status === 409 && err.errorCode === 'incident_stale') {
        setStale(true)
        setError(STALE_MESSAGE)
      } else if (err instanceof ApiError && err.status === 409 && err.errorCode === 'incident_entry_limit') {
        setError(ENTRY_LIMIT_MESSAGE)
      } else {
        setError(toErrorMessage(err))
      }
    } finally {
      onWrite?.()
      setBusy(false)
    }
  }

  const stopEditing = () => {
    setEditing(false)
    setStale(false)
    setShowLatest(false)
    setError(null)
  }

  const remove = (kind: 'entries' | 'events' | 'alerts' | 'snapshots', id: number, message: string) => {
    if (!window.confirm(message)) return
    void run(async () => {
      try {
        await deleteIncident(incident.id, kind, id)
      } catch (err) {
        if (!(err instanceof ApiError) || err.status !== 404) throw err
        // 子の行だけが消えた場合も 404 なので、詳細を読み直して区別する。
        await reload()
        setFeedback(kind === 'entries' ? 'すでに削除されていました' : 'すでに外されていました')
        return
      }
      await reload()
    })
  }

  const unlink = (kind: 'events' | 'alerts' | 'snapshots', id: number) => (
    <button type="button" className="btn btn--gray" disabled={busy} onClick={() => remove(kind, id, kind === 'snapshots'
      ? '紐付けを外しますか？ スナップショットと保存結果は、次の保持期間の削除から通常の設定に従って削除の対象になります。'
      : '紐付けを外しますか？ インシデントから写しも削除されます。')}>外す</button>
  )

  return (
    <article>
      <h2>{incident.title}</h2>
      {error && <p className="error-banner" role="alert">{error}</p>}
      {feedback && <p className="hint" role="status">{feedback}</p>}
      {stale && (
        <button type="button" className="btn" disabled={busy} onClick={() => void run(async () => {
          await reload(true)
          setStale(false)
          setShowLatest(true)
        })}>読み直す</button>
      )}
      {editing && canWrite ? (
        <>
          <IncidentEditor ref={editorRef} incident={incident} disabled={busy} stale={stale} onCancel={stopEditing} onSave={(patch) =>
            void run(async () => {
              onChange(await patchIncident(incident.id, patch))
              stopEditing()
            })}
          />
          {showLatest && (
            <details className="incident-latest" open>
              <summary>読み直した最新の内容</summary>
              <IncidentFields incident={incident} format={format} />
              <p className="hint">要約</p>
              <p className="incident-text">{incident.summary || '—'}</p>
            </details>
          )}
        </>
      ) : (
        <>
          <IncidentFields incident={incident} format={format} />
          {canWrite && <button type="button" className="btn" disabled={busy} onClick={() => setEditing(true)}>編集</button>}
          <h3>要約</h3>
          <p className="incident-text">{incident.summary || '—'}</p>
        </>
      )}

      <h3>経過</h3>
      <Records empty="経過の記録はありません。">
        {incident.entries.map((entry) => (
          <li key={entry.id}>
            <div className="incident-actions">
              <span className="badge">{ENTRY_KIND_LABELS[entry.kind]}</span>
              <span className="hint">{format(entry.created_at)} ・ {entry.author}</span>
            </div>
            <p className="incident-text">{entry.deleted_at ? `（${entry.deleted_by}が削除しました）` : entry.body}</p>
            {canDelete && !entry.deleted_at && (
              <button type="button" className="btn btn--danger" disabled={busy}
                onClick={() => remove('entries', entry.id, 'この経過の本文を削除しますか？')}>削除</button>
            )}
          </li>
        ))}
      </Records>
      {canWrite && (
        <form className="incident-note-form" onSubmit={(event) => {
          event.preventDefault()
          if (!note.trim()) return
          void run(async () => {
            const entry = await addIncidentEntry(incident.id, note)
            setNote('')
            onChange({ ...incident, entries: [...incident.entries, entry] })
            try {
              await reload()
            } catch (err) {
              if (err instanceof ApiError && err.status === 404) throw err
              setError('メモを追加しました。最新の経過を読み込めませんでした。')
            }
          })
        }}>
          <label>メモ<textarea rows={3} maxLength={4000} value={note} disabled={busy} onChange={(event) => setNote(event.target.value)} /></label>
          <div><button type="submit" className="btn btn--filled" disabled={busy || !note.trim()}>メモを追加</button></div>
        </form>
      )}

      <h3>紐付けたイベント</h3>
      <Records empty="紐付けたイベントはありません。">
        {incident.events.map((event) => (
          <li key={event.id}>
            <strong>{event.event_type}</strong>
            <div className="hint">{[format(event.occurred_at), event.vcenter_name, event.entity_name || event.entity_moid, event.user_name].filter(Boolean).join(' ・ ')}</div>
            <div className="incident-actions"><SeverityBadge severity={event.severity} /><ScoreBadge score={event.notable_score} /></div>
            <p className="incident-text">{event.message}</p>
            {event.user_comment && <p className="incident-text">運用メモ{' '}{event.user_comment}</p>}
            <div className="incident-actions">
              <SourceTimelineLink source={event} />
              {canWrite && unlink('events', event.id)}
            </div>
          </li>
        ))}
      </Records>

      <h3>紐付けた通知</h3>
      <Records empty="紐付けた通知はありません。">
        {incident.alerts.map((alert) => (
          <li key={alert.id}>
            <strong>{alert.rule_name || `ルール #${alert.rule_id}`}</strong>
            <div className="hint">{[format(alert.occurred_at), alert.vcenter_name, alert.entity_name || alert.context_key].filter(Boolean).join(' ・ ')}</div>
            <div className="incident-actions">
              <SeverityBadge severity={alert.alert_level} />
              <span>{alertStateLabel(alert.state)}</span>
            </div>
            <div className="incident-actions">
              <SourceTimelineLink source={alert} omitEntity={alert.rule_type === 'event_pattern'} />
              {canWrite && unlink('alerts', alert.id)}
            </div>
          </li>
        ))}
      </Records>

      <h3>紐付けたスナップショット</h3>
      <Records empty="紐付けたスナップショットはありません。">
        {incident.snapshots.map((snapshot) => (
          <li key={snapshot.id}>
            <strong className="incident-text">{snapshot.operator_note}</strong>
            <div className="hint">{format(snapshot.from_time)} ～ {format(snapshot.to_time)}（保存 {format(snapshot.created_at)}）</div>
            <div className="incident-actions">
              <button type="button" className="btn btn--gray" onClick={() => onOpenSnapshot(snapshot.snapshot_id)}>タイムラインで開く</button>
              {canWrite && unlink('snapshots', snapshot.id)}
            </div>
            <TimelineExportControls
              activity={exportActivity}
              source={snapshot.has_result ? { snapshotId: snapshot.snapshot_id } : null}
              sourceLabel={`スナップショット「${snapshot.operator_note}」`}
              timeZone={timeZone}
              unavailableReason={snapshot.has_result ? undefined : '結果が保存されていません。'}
            />
          </li>
        ))}
      </Records>

      {canDelete && (
        <button type="button" className="btn btn--danger" disabled={busy} onClick={() => {
          if (!window.confirm('インシデントを削除しますか？ 経過と紐付けも削除されます。')) return
          void run(async () => {
            await deleteIncident(incident.id)
            onDeleted()
          })
        }}>インシデントを削除</button>
      )}
    </article>
  )
}

function IncidentFields({ incident, format }: { incident: IncidentDetail; format: (iso: string) => string }) {
  return (
    <dl className="incident-fields">
      <div><dt>状態</dt><dd><span className={INCIDENT_STATUS_BADGES[incident.status]}>{INCIDENT_STATUS_LABELS[incident.status]}</span></dd></div>
      <div><dt>重大度</dt><dd><SeverityBadge severity={incident.level} /></dd></div>
      <div><dt>担当</dt><dd>{incident.assignee || '—'}</dd></div>
      <div><dt>開始時刻</dt><dd>{incident.started_at ? format(incident.started_at) : '—'}</dd></div>
    </dl>
  )
}

function Records({ empty, children }: { empty: string; children: ReactNode[] }) {
  return children.length ? <ul className="incident-records">{children}</ul> : <p className="hint">{empty}</p>
}

function SourceTimelineLink({ source, omitEntity = false }: {
  source: Pick<IncidentDetail['events'][number] | IncidentDetail['alerts'][number],
  'source_exists' | 'occurred_at' | 'vcenter_id' | 'entity_name' | 'entity_moid'>
  omitEntity?: boolean
}) {
  if (!source.source_exists) return <span className="hint">元の行は削除されています</span>
  const href = timelineEntryHash({
    at: source.occurred_at,
    vcenterId: source.vcenter_id,
    entity: omitEntity ? null : source.entity_name,
    entityMoid: omitEntity || !source.vcenter_id ? null : source.entity_moid,
  })
  return href && <a className="timeline-link" href={href}>前後 30 分のタイムライン</a>
}

function IncidentEditor({ ref, incident, disabled, stale, onCancel, onSave }: {
  ref: Ref<IncidentDraftHandle>
  incident: IncidentDetail
  disabled: boolean
  stale: boolean
  onCancel: () => void
  onSave: (patch: IncidentPatch) => void
}) {
  const { me } = useAuth()
  const { timeZone } = useTimeZone()
  const originalStart = incident.started_at ? utcIsoToZonedLocalDateTimeInput(incident.started_at, timeZone) : ''
  const latest = {
    title: incident.title,
    status: incident.status,
    level: incident.level,
    assignee: incident.assignee ?? '',
    started: originalStart,
    summary: incident.summary,
  }
  const [draft, setDraft] = useState<Partial<typeof latest>>({})
  const { title, status, level, assignee, started, summary } = { ...latest, ...draft }
  const [invalidStart, setInvalidStart] = useState(false)
  const hasDraft = (Object.keys(draft) as (keyof typeof draft)[]).some((key) => draft[key] !== latest[key])
  useImperativeHandle(ref, () => ({ hasDraft: () => hasDraft }), [hasDraft])

  const edit = <K extends keyof typeof latest>(field: K, value: (typeof latest)[K]) => {
    setDraft((previous) => {
      const next = { ...previous }
      if (value === latest[field]) delete next[field]
      else next[field] = value
      return next
    })
  }

  const assignSelf = () => {
    const { display_name: displayName, username } = me
    const available = 256 - Array.from(username).length - 2
    const name = displayName && displayName !== username && available > 0
      ? `${Array.from(displayName).slice(0, available).join('')}（${username}）`
      : username
    edit('assignee', name)
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!title.trim() || stale || disabled) return
    const patch: IncidentPatch = { revision: incident.revision }
    if (title !== incident.title) patch.title = title
    if (status !== incident.status) patch.status = status
    if (level !== incident.level) patch.level = level
    if (assignee !== (incident.assignee ?? '')) patch.assignee = assignee || null
    if (summary !== incident.summary) patch.summary = summary
    if (started !== originalStart) {
      const utc = started ? zonedLocalDateTimeToUtcIso(started, timeZone) : null
      if (started && utc === null) {
        setInvalidStart(true)
        return
      }
      patch.started_at = utc
    }
    onSave(patch)
  }

  return (
    <form className="incident-editor" onSubmit={submit}>
      <label>件名<input required maxLength={200} value={title} disabled={disabled} onChange={(event) => edit('title', event.target.value)} /></label>
      <div className="incident-fields">
        <label>状態
          <select value={status} disabled={disabled} onChange={(event) => edit('status', event.target.value as IncidentStatus)}>
            {Object.entries(INCIDENT_STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label>重大度
          <select value={level ?? ''} disabled={disabled} onChange={(event) => edit('level', event.target.value as IncidentLevel || null)}>
            <option value="">指定なし</option>
            {incidentLevelSchema.options.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <div>
          <label>担当<input value={assignee} disabled={disabled} onChange={(event) => edit('assignee', Array.from(event.target.value).slice(0, 256).join(''))} /></label>
          {me.auth_enabled && (
            <button type="button" className="btn" disabled={disabled} onClick={assignSelf}>自分</button>
          )}
        </div>
        <label>開始時刻（{timeZone}）
          <input type="datetime-local" value={started} disabled={disabled} onChange={(event) => {
            edit('started', event.target.value)
            setInvalidStart(false)
          }} />
        </label>
      </div>
      {invalidStart && <p className="error-banner" role="alert">開始時刻を確認してください。</p>}
      <label>要約<textarea rows={5} maxLength={20_000} value={summary} disabled={disabled} onChange={(event) => edit('summary', event.target.value)} /></label>
      <div className="incident-actions">
        <button type="submit" className="btn btn--filled" disabled={disabled || stale || !title.trim()}>保存</button>
        <button type="button" className="btn" disabled={disabled} onClick={onCancel}>キャンセル</button>
      </div>
    </form>
  )
}
