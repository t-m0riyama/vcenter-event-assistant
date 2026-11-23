import type { TimelineHighlights as Highlights, TimelineViewItem } from '../../api/schemas'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { KIND_LABELS, LEVEL_BADGE_CLASS, LEVEL_LABELS, titleStartsWithEntity } from './timelineLabels'

type Props = {
  highlights: Highlights
  /** リストに載っている行の id。打ち切りで載っていない行は、クリックで移動できない。 */
  listedIds: ReadonlySet<string>
  timeZone: string
  onRevealItem: (id: string) => void
  onFilterEntity: (entityName: string, vcenterId: string | null | undefined, entityMoid?: string | null) => void
}

function firstSignalLabel(item: TimelineViewItem): string {
  // ログの行はタイトルが「ホスト名 ログの種類」で、対象名が重なる。重ねて出さない
  if (titleStartsWithEntity(item.title, item.entity_name)) return item.title
  return [item.entity_name, item.title].filter(Boolean).join(' / ')
}

/** ハイライト: 最初の兆候・影響の大きい対象・初めて出たイベント種別。データが無い項目は出さない。 */
export function TimelineHighlights({ highlights, listedIds, timeZone, onRevealItem, onFilterEntity }: Props) {
  const first = highlights.first_signal ?? null
  const top = highlights.top_entities
  const fresh = highlights.new_event_types
  if (!first && top.length === 0 && fresh.length === 0) return null

  return (
    <section className="timeline-highlights" aria-label="ハイライト">
      <h3 className="timeline-section-title">ハイライト</h3>
      <div className="timeline-highlights__grid">
        {first ? (
          <div className="timeline-highlights__card">
            <h4>最初の兆候</h4>
            <p>
              {formatIsoInTimeZone(first.timestamp_utc, timeZone)}{' '}
              <span className={LEVEL_BADGE_CLASS[first.level]}>{LEVEL_LABELS[first.level]}</span>{' '}
              <span className="timeline-highlights__kind">{KIND_LABELS[first.kind]}</span>
            </p>
            {listedIds.has(first.id) ? (
              <button type="button" className="btn btn--gray timeline-highlights__link" onClick={() => onRevealItem(first.id)}>
                {firstSignalLabel(first)}
              </button>
            ) : (
              <>
                <p>{firstSignalLabel(first)}</p>
                <p className="hint">この出来事は表示件数の上限により一覧に含まれていません。</p>
              </>
            )}
          </div>
        ) : null}
        {top.length > 0 ? (
          <div className="timeline-highlights__card">
            <h4>影響の大きい対象</h4>
            <ul>
              {top.map((e) => (
                <li key={JSON.stringify([e.vcenter_id, e.entity_name, e.entity_moid])}>
                  <button
                    type="button"
                    className="btn btn--gray timeline-highlights__link"
                    onClick={() => onFilterEntity(e.entity_name, e.vcenter_id, e.vcenter_id ? e.entity_moid : undefined)}
                  >
                    {e.entity_name}
                  </button>{' '}
                  <span className="timeline-highlights__meta">
                    {e.vcenter_name ? `${e.vcenter_name}・` : ''}
                    {e.item_count} 件・最初 {formatIsoInTimeZone(e.first_seen_utc, timeZone)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {fresh.length > 0 ? (
          <div className="timeline-highlights__card">
            <h4>初めて出たイベント種別</h4>
            <ul>
              {fresh.map((t) => (
                <li key={t.event_type}>
                  <span className="timeline-highlights__type">{t.event_type}</span>{' '}
                  <span className="timeline-highlights__meta">
                    {t.count} 件・最大スコア {t.max_score}・最初 {formatIsoInTimeZone(t.first_seen_utc, timeZone)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </section>
  )
}
