import type { IncidentTimelineManualSnapshotListItem } from '../../api/schemas'
import { useAuth } from '../../auth/useAuth'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import type { useTimelineSnapshots } from '../../hooks/useTimelineSnapshots'

type Props = {
  snapshots: ReturnType<typeof useTimelineSnapshots>
  /** 表示中の結果があり、保存できる状態か。 */
  canSaveNow: boolean
  timeZone: string
  onOpenSnapshotInMetrics?: (item: IncidentTimelineManualSnapshotListItem) => void
}

/** 画面下部の折りたたみ（既定は閉じる）。手動スナップショットの保存・一覧・グラフで開く。 */
export function TimelineSnapshotSection({ snapshots: s, canSaveNow, timeZone, onOpenSnapshotInMetrics }: Props) {
  // 手動スナップショットの保存は operator 以上（閲覧は viewer でもできる）
  const canSave = useAuth().hasRole('operator')
  return (
    <section className="timeline-snapshots" aria-label="スナップショット">
      <h3 className="timeline-section-title">
        <button
          type="button"
          className="timeline-snapshots__toggle"
          aria-expanded={s.open}
          aria-controls="timeline-snapshots-body"
          onClick={() => s.setOpen(!s.open)}
        >
          <span aria-hidden="true">{s.open ? '▾' : '▸'}</span> スナップショット
        </button>
      </h3>
      {s.open ? (
        <div id="timeline-snapshots-body">
          {canSave ? (
            <div className="timeline-snapshots__save">
              <label className="timeline-snapshots__note">
                運用メモ（必須）
                <input
                  type="text"
                  value={s.operatorNote}
                  onChange={(e) => s.setOperatorNote(e.target.value)}
                  disabled={s.saving}
                />
              </label>
              <button
                type="button"
                className="btn btn--gray"
                onClick={() => void s.save()}
                disabled={s.saving || !canSaveNow || s.operatorNote.trim() === ''}
              >
                スナップショットを保存
              </button>
              <p className="hint">表示中の期間と vCenter の条件を保存します（結果そのものは保存しません）。</p>
            </div>
          ) : null}
          {s.items.length === 0 ? (
            <p className="hint">{s.listLoaded ? '保存済みスナップショットはまだありません。' : '読み込み中…'}</p>
          ) : (
            <ul className="timeline-snapshots__list">
              {s.items.map((item) => (
                <li key={item.snapshot_id}>
                  <button
                    type="button"
                    className="btn btn--gray"
                    aria-pressed={s.selectedId === item.snapshot_id}
                    onClick={() => s.select(item)}
                  >
                    {item.operator_note}
                  </button>{' '}
                  {onOpenSnapshotInMetrics ? (
                    <button type="button" className="btn btn--gray" onClick={() => onOpenSnapshotInMetrics(item)}>
                      グラフで開く
                    </button>
                  ) : null}{' '}
                  <span className="timeline-snapshots__time">({formatIsoInTimeZone(item.timestamp_utc, timeZone)})</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </section>
  )
}
