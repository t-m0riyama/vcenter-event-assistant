import type { IncidentTimelineManualSnapshotListItem } from '../../api/schemas'

type TimelineSnapshotActionsProps = {
  loading: boolean
  savingSnapshot: boolean
  hasTimeline: boolean
  operatorNote: string
  setOperatorNote: (value: string) => void
  onGenerateTimeline: () => void | Promise<void>
  onSaveSnapshot: () => void | Promise<void>
  manualSnapshotAuditItems: IncidentTimelineManualSnapshotListItem[]
  selectedManualSnapshotId: string | null
  setSelectedManualSnapshotId: (id: string | null) => void
  onLoadTimelineFromSnapshot: (item: IncidentTimelineManualSnapshotListItem) => void | Promise<void>
  onOpenSnapshotInMetrics?: (item: IncidentTimelineManualSnapshotListItem) => void
}

/** タイムライン生成・スナップショット保存・読み込み操作 UI。 */
export function TimelineSnapshotActions({
  loading,
  savingSnapshot,
  hasTimeline,
  operatorNote,
  setOperatorNote,
  onGenerateTimeline,
  onSaveSnapshot,
  manualSnapshotAuditItems,
  selectedManualSnapshotId,
  setSelectedManualSnapshotId,
  onLoadTimelineFromSnapshot,
  onOpenSnapshotInMetrics,
}: TimelineSnapshotActionsProps) {
  return (
    <>
      <div className="timeline-panel__actions">
        <button
          type="button"
          className="btn btn--filled"
          onClick={() => void onGenerateTimeline()}
          disabled={loading}
          aria-busy={loading ? 'true' : 'false'}
        >
          {loading ? 'タイムライン生成中' : 'タイムラインを生成'}
        </button>
      </div>

      {hasTimeline ? (
        <section className="timeline-panel__section" aria-label="手動スナップショット保存">
          <label className="timeline-panel__threshold-field">
            運用メモ（必須）
            <input
              type="text"
              value={operatorNote}
              onChange={(e) => setOperatorNote(e.target.value)}
              disabled={loading || savingSnapshot}
            />
          </label>
          <div className="timeline-panel__actions">
            <button
              type="button"
              className="btn btn--gray"
              onClick={() => void onSaveSnapshot()}
              disabled={loading || savingSnapshot || operatorNote.trim() === ''}
            >
              スナップショットを保存
            </button>
          </div>
        </section>
      ) : null}

      <section className="timeline-panel__section" aria-label="手動スナップショット監査ビュー">
        <h3>手動スナップショット監査ビュー</h3>
        {manualSnapshotAuditItems.length === 0 ? (
          <p className="hint">保存済みスナップショットはまだありません。</p>
        ) : (
          <>
            <ul>
              {manualSnapshotAuditItems.map((item) => (
                <li key={item.snapshot_id}>
                  <button
                    type="button"
                    className="btn btn--gray"
                    onClick={() => {
                      setSelectedManualSnapshotId(item.snapshot_id)
                      void onLoadTimelineFromSnapshot(item)
                    }}
                    aria-pressed={selectedManualSnapshotId === item.snapshot_id}
                  >
                    {item.operator_note}
                  </button>{' '}
                  {onOpenSnapshotInMetrics ? (
                    <button
                      type="button"
                      className="btn btn--gray"
                      onClick={() => onOpenSnapshotInMetrics(item)}
                    >
                      グラフで開く
                    </button>
                  ) : null}{' '}
                  <span>({item.timestamp_utc})</span>
                </li>
              ))}
            </ul>
            {selectedManualSnapshotId ? (
              <section aria-label="選択中スナップショット">
                <h4>選択中スナップショット</h4>
                {(() => {
                  const selected = manualSnapshotAuditItems.find(
                    (item) => item.snapshot_id === selectedManualSnapshotId,
                  )
                  if (!selected) {
                    return <p className="hint">選択中のスナップショットは見つかりません。</p>
                  }
                  return (
                    <p>
                      <strong>{selected.operator_note}</strong> ({selected.timestamp_utc})
                    </p>
                  )
                })()}
              </section>
            ) : null}
          </>
        )}
      </section>
    </>
  )
}
