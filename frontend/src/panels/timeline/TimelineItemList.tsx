import { useEffect, useRef } from 'react'

import type { TimelineViewItem } from '../../api/schemas'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { ScoreBadge } from '../../components/badges'
import type { GuideLoader } from './eventTypeGuideLoader'
import { TimelineEventGuide } from './TimelineEventGuide'
import { alertStateLabel, excerpt, KIND_LABELS, LEVEL_BADGE_CLASS, LEVEL_LABELS } from './timelineLabels'
import { correlationHashForItem } from './timelineModel'

type Props = {
  items: readonly TimelineViewItem[]
  timeZone: string
  nearestAnchorId: string | null
  expandedIds: ReadonlySet<string>
  onToggle: (id: string) => void
  /** 最初の兆候などからの移動の要求。`nonce` が変わるたびにスクロールしてフォーカスする。 */
  reveal: { id: string; nonce: number } | null
  guideLoader: GuideLoader
  onFilterEntity: (entityName: string, vcenterId: string | null | undefined) => void
  onSetAnchor: (timestampUtc: string) => void
}

function rowDomId(id: string): string {
  return `timeline-item-${id.replace(/[^A-Za-z0-9_-]/g, '_')}`
}

function ItemRow({
  item,
  timeZone,
  isNearest,
  expanded,
  isRevealed,
  onToggle,
  guideLoader,
  onFilterEntity,
  onSetAnchor,
}: {
  item: TimelineViewItem
  timeZone: string
  isNearest: boolean
  expanded: boolean
  isRevealed: boolean
  onToggle: () => void
  guideLoader: GuideLoader
  onFilterEntity: Props['onFilterEntity']
  onSetAnchor: Props['onSetAnchor']
}) {
  const domId = rowDomId(item.id)
  const eventsHref = correlationHashForItem('events', item)
  const logsHref = correlationHashForItem('logs', item)
  const merged = item.count > 1
  const classes = [
    'timeline-row',
    `timeline-row--${item.level}`,
    isNearest ? 'timeline-row--nearest' : '',
    isRevealed ? 'timeline-row--revealed' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <li id={domId} className={classes}>
      <button
        type="button"
        id={`${domId}-button`}
        className="timeline-row__summary"
        aria-expanded={expanded}
        aria-controls={`${domId}-detail`}
        onClick={onToggle}
      >
        <span className="timeline-row__time">
          {formatIsoInTimeZone(item.timestamp_utc, timeZone)}
        </span>
        <span className="timeline-row__chips">
          <span className="timeline-row__kind">{KIND_LABELS[item.kind]}</span>
          <span className={LEVEL_BADGE_CLASS[item.level]}>{LEVEL_LABELS[item.level]}</span>
          {merged ? (
            <span className="timeline-row__count">
              ×{item.count}
              {item.end_utc ? `（最後 ${formatIsoInTimeZone(item.end_utc, timeZone)}）` : ''}
            </span>
          ) : null}
          {isNearest ? <span className="timeline-row__anchor-mark">◆ 起点に最も近い</span> : null}
        </span>
        {item.entity_name ? <span className="timeline-row__entity">{item.entity_name}</span> : null}
        <span className="timeline-row__title">{item.title}</span>
        {item.detail ? <span className="timeline-row__excerpt">{excerpt(item.detail)}</span> : null}
      </button>
      {expanded ? (
        <div id={`${domId}-detail`} className="timeline-row__detail" role="region" aria-label={`${item.title} の詳細`}>
          <dl className="timeline-row__facts">
            <dt>メッセージ</dt>
            <dd className="timeline-row__message">{item.detail?.trim() ? item.detail : '—'}</dd>
            <dt>vCenter</dt>
            <dd>{item.vcenter_name ?? '—'}</dd>
            {item.entity_name ? (
              <>
                <dt>対象</dt>
                <dd>
                  {item.entity_name}
                  {item.entity_type ? `（${item.entity_type}）` : ''}
                </dd>
              </>
            ) : null}
            <dt>スコア</dt>
            <dd>{item.score != null ? <ScoreBadge score={item.score} /> : '—'}</dd>
            {item.kind === 'alert' ? (
              <>
                <dt>ルール名</dt>
                <dd>{item.ref.alert_rule_name ?? '—'}</dd>
                <dt>状態</dt>
                <dd>{alertStateLabel(item.ref.alert_state)}</dd>
              </>
            ) : null}
            {merged ? (
              <>
                <dt>まとめた件数</dt>
                <dd>
                  {item.count} 件（{formatIsoInTimeZone(item.timestamp_utc, timeZone)}
                  {item.end_utc ? ` ～ ${formatIsoInTimeZone(item.end_utc, timeZone)}` : ''}）
                </dd>
              </>
            ) : null}
          </dl>
          {item.kind === 'event' ? <TimelineEventGuide item={item} loader={guideLoader} /> : null}
          <div className="timeline-row__actions">
            {item.entity_name ? (
              <button type="button" className="btn btn--gray" onClick={() => onFilterEntity(item.entity_name!, item.vcenter_id)}>
                この対象で絞る
              </button>
            ) : null}
            <button type="button" className="btn btn--gray" onClick={() => onSetAnchor(item.timestamp_utc)}>
              ここを起点にする
            </button>
            {eventsHref ? (
              <a className="btn btn--gray" href={eventsHref}>
                イベントで開く
              </a>
            ) : null}
            {logsHref ? (
              <a className="btn btn--gray" href={logsHref}>
                ログで開く
              </a>
            ) : null}
          </div>
        </div>
      ) : null}
    </li>
  )
}

/** 時系列リスト（縦）。行を開くと詳細と操作が出る。 */
export function TimelineItemList({
  items,
  timeZone,
  nearestAnchorId,
  expandedIds,
  onToggle,
  reveal,
  guideLoader,
  onFilterEntity,
  onSetAnchor,
}: Props) {
  const lastNonce = useRef(0)
  useEffect(() => {
    if (!reveal || reveal.nonce === lastNonce.current) return
    lastNonce.current = reveal.nonce
    const button = document.getElementById(`${rowDomId(reveal.id)}-button`)
    button?.scrollIntoView?.({ block: 'center' })
    button?.focus()
  }, [reveal])

  return (
    <ol className="timeline-list" aria-label="出来事の時系列">
      {items.map((item) => (
        <ItemRow
          key={item.id}
          item={item}
          timeZone={timeZone}
          isNearest={item.id === nearestAnchorId}
          expanded={expandedIds.has(item.id)}
          isRevealed={reveal?.id === item.id}
          onToggle={() => onToggle(item.id)}
          guideLoader={guideLoader}
          onFilterEntity={onFilterEntity}
          onSetAnchor={onSetAnchor}
        />
      ))}
    </ol>
  )
}
