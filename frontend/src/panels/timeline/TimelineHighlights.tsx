import { useId } from 'react'
import type { TimelineConfigChange, TimelineDetectedPattern, TimelineHighlights as Highlights, TimelineViewItem } from '../../api/schemas'
import { formatIsoInTimeZone, parseApiUtcInstantMs } from '../../datetime/formatIsoInTimeZone'
import { CONFIG_CHANGE_LABELS, KIND_LABELS, LEVEL_BADGE_CLASS, LEVEL_LABELS, titleStartsWithEntity } from './timelineLabels'

type Props = {
  highlights: Highlights
  patternTitles: ReadonlyMap<string, string>
  /** リストに載っている行の id。打ち切りで載っていない行は、クリックで移動できない。 */
  listedIds: ReadonlySet<string>
  includesEvents: boolean
  anchorUtc: string | null
  timeZone: string
  onRevealItem: (id: string) => void
  onFilterEntity: (entityName: string, vcenterId: string | null | undefined, entityMoid?: string | null) => void
  onSetAnchor: (timestampUtc: string) => void
}

function firstSignalLabel(item: TimelineViewItem): string {
  // ログの行はタイトルが「ホスト名 ログの種類」で、対象名が重なる。重ねて出さない
  if (titleStartsWithEntity(item.title, item.entity_name)) return item.title
  return [item.entity_name, item.title].filter(Boolean).join(' / ')
}

function DetectedPatternItem({ pattern, timeZone, onSetAnchor }: {
  pattern: TimelineDetectedPattern
  timeZone: string
  onSetAnchor: Props['onSetAnchor']
}) {
  const id = useId()
  const titleId = `${id}-title`
  const entityId = `${id}-entity`
  const sameTime = parseApiUtcInstantMs(pattern.first_utc) === parseApiUtcInstantMs(pattern.last_utc)
  const descriptionIds = `${titleId} ${entityId}`

  return (
    <li>
      <p>
        <strong id={titleId}>{pattern.title}</strong>{' '}
        <span className={LEVEL_BADGE_CLASS[pattern.level]}>{LEVEL_LABELS[pattern.level]}</span>
      </p>
      <p className="timeline-highlights__meta">
        <span id={entityId}>{pattern.entity_name || pattern.entity_moid}</span>
        {pattern.vcenter_name ? <>・<span>{pattern.vcenter_name}</span></> : null}
        ・<span>{pattern.event_count} 件</span>
      </p>
      <p className="timeline-highlights__meta">
        {formatIsoInTimeZone(pattern.first_utc, timeZone)}
        {sameTime ? null : ` ～ ${formatIsoInTimeZone(pattern.last_utc, timeZone)}`}
      </p>
      <details>
        <summary aria-describedby={descriptionIds}>説明</summary>
        <p className="timeline-highlights__meta">{pattern.description}</p>
      </details>
      <button
        type="button"
        className="btn btn--gray timeline-highlights__link"
        aria-describedby={descriptionIds}
        onClick={() => onSetAnchor(pattern.first_utc)}
      >
        ここを起点にする
      </button>
    </li>
  )
}

function ConfigChangeItem({ change, listedIds, timeZone, onRevealItem, onFilterEntity, onSetAnchor }: {
  change: TimelineConfigChange
} & Pick<Props, 'listedIds' | 'timeZone' | 'onRevealItem' | 'onFilterEntity' | 'onSetAnchor'>) {
  const target = change.entity_name || change.entity_moid
  const vcenter = change.vcenter_name || change.vcenter_id
  const sameTime = parseApiUtcInstantMs(change.first_utc) === parseApiUtcInstantMs(change.last_utc)
  const lastTime = formatIsoInTimeZone(change.last_utc, timeZone)
  const time = sameTime ? lastTime : `${formatIsoInTimeZone(change.first_utc, timeZone)} ～ ${lastTime}`
  const users = change.user_names.join('、')
  const context = [change.label, target, vcenter, users, time].filter(Boolean).join('・')
  const eventId = change.event_ids.find((id) => listedIds.has(`event:${id}`))
  const filterMoid = change.vcenter_id ? change.entity_moid : null

  return (
    <li>
      <p><strong>{change.label}</strong></p>
      <p className="timeline-highlights__meta">
        {[target, vcenter, `${change.event_count} 件`].filter(Boolean).join('・')}
      </p>
      {users ? (
        <p className="timeline-highlights__meta">利用者 {users}</p>
      ) : null}
      <p className="timeline-highlights__meta">{time}</p>
      <div className="timeline-highlights__actions">
        <button
          type="button"
          className="btn btn--gray timeline-highlights__link"
          aria-label={`ここを起点にする（${context}）`}
          onClick={() => onSetAnchor(change.last_utc)}
        >
          ここを起点にする
        </button>
        {change.entity_name || filterMoid ? (
          <button
            type="button"
            className="btn btn--gray timeline-highlights__link"
            aria-label={`この対象で絞る（${context}）`}
            onClick={() => onFilterEntity(change.entity_name ?? '', change.vcenter_id, filterMoid)}
          >
            この対象で絞る
          </button>
        ) : null}
        {eventId !== undefined ? (
          <button
            type="button"
            className="btn btn--gray timeline-highlights__link"
            aria-label={`一覧の行へ移動（${context}）`}
            onClick={() => onRevealItem(`event:${eventId}`)}
          >
            一覧の行へ移動
          </button>
        ) : null}
      </div>
    </li>
  )
}

function ConfigChangesCard({ highlights, anchorUtc, ...actions }: Pick<Props,
  'highlights' | 'anchorUtc' | 'listedIds' | 'timeZone' | 'onRevealItem' | 'onFilterEntity' | 'onSetAnchor'
>) {
  const headingId = useId()
  const changes = highlights.config_changes
  const counts = highlights.config_change_counts
  const countedKinds = [
    ...Array.from(CONFIG_CHANGE_LABELS.keys()).filter((kind) => Object.hasOwn(counts, kind)),
    ...Object.keys(counts).filter((kind) => !CONFIG_CHANGE_LABELS.has(kind)),
  ]
  return (
    <section className="timeline-highlights__card timeline-highlights__grouped" aria-labelledby={headingId}>
      <h4 id={headingId}>構成変更</h4>
      {countedKinds.length > 0 ? (
        <p className="timeline-highlights__meta">
          {countedKinds.map((kind) => `${CONFIG_CHANGE_LABELS.get(kind) ?? kind} ${counts[kind]} 件`).join('・')}
        </p>
      ) : null}
      {changes == null ? (
        <p>判定していません</p>
      ) : changes.length === 0 ? (
        <p>{anchorUtc ? '起点までに構成変更はありません' : 'この期間に構成変更はありません'}</p>
      ) : (
        <ul>
          {changes.map((change) => (
            <ConfigChangeItem
              key={JSON.stringify([change.kind, change.vcenter_id, change.event_ids[0]])}
              change={change}
              {...actions}
            />
          ))}
        </ul>
      )}
      {changes && highlights.config_changes_total > changes.length ? (
        <p className="hint">全 {highlights.config_changes_total} 件のうち、新しい {changes.length} 件を表示しています</p>
      ) : null}
      {highlights.config_changes_truncated ? <p className="hint">古い構成変更は省きました</p> : null}
    </section>
  )
}

export function TimelineHighlights({
  highlights, patternTitles, listedIds, includesEvents, anchorUtc, timeZone, onRevealItem, onFilterEntity, onSetAnchor,
}: Props) {
  const headingId = useId()
  const first = highlights.first_signal ?? null
  const top = highlights.top_entities
  const fresh = highlights.new_event_types
  const patterns = highlights.detected_patterns
  const remaining = highlights.detected_patterns_total - patterns.length
  const omitted = highlights.omitted_patterns
  if (!includesEvents && !first && top.length === 0 && fresh.length === 0 && patterns.length === 0 && omitted.length === 0) return null

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
      {patterns.length > 0 || includesEvents ? (
        <div className="timeline-highlights__grid">
          {patterns.length > 0 ? (
            <section className="timeline-highlights__card timeline-highlights__grouped" aria-labelledby={headingId}>
              <h4 id={headingId}>検知した障害パターン</h4>
              <ul>
                {patterns.map((pattern) => (
                  <DetectedPatternItem
                    key={JSON.stringify([
                      pattern.pattern_id, pattern.vcenter_id, pattern.entity_moid, pattern.first_utc,
                      pattern.event_ids[0] ?? pattern.last_utc,
                    ])}
                    pattern={pattern}
                    timeZone={timeZone}
                    onSetAnchor={onSetAnchor}
                  />
                ))}
              </ul>
              {remaining > 0 ? <p className="hint">ほかに {remaining} 件</p> : null}
            </section>
          ) : null}
          {includesEvents ? (
            <ConfigChangesCard
              highlights={highlights}
              anchorUtc={anchorUtc}
              listedIds={listedIds}
              timeZone={timeZone}
              onRevealItem={onRevealItem}
              onFilterEntity={onFilterEntity}
              onSetAnchor={onSetAnchor}
            />
          ) : null}
        </div>
      ) : null}
      {omitted.length > 0 ? (
        <p className="hint timeline-highlights__omitted" role="note">
          件数が多すぎるため判定しなかったパターンがあります（{omitted.map((id) => patternTitles.get(id) ?? id).join('、')}）。
        </p>
      ) : null}
    </section>
  )
}
