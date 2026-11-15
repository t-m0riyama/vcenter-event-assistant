import { useEffect, useRef } from 'react'

import type { MetricsFocus } from '../../hooks/metricsReplay'
import type { TimelineViewItem } from '../../api/schemas'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { ScoreBadge } from '../../components/badges'
import type { GuideLoader } from './eventTypeGuideLoader'
import { TimelineEventGuide } from './TimelineEventGuide'
import { alertStateLabel } from '../../alerts/alertStateLabel'
import { excerpt, KIND_LABELS, LEVEL_BADGE_CLASS, LEVEL_LABELS } from './timelineLabels'
import { correlationHashForItem, formatDurationMs, intervalDurationMs, metricsFocusForItem } from './timelineModel'

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
  /** 渡すと、vCenter のある行に「グラフで開く」を出す。 */
  onOpenInMetrics?: (focus: MetricsFocus) => void
}

function rowDomId(id: string): string {
  return `timeline-item-${id.replace(/[^A-Za-z0-9_-]/g, '_')}`
}

/** サーバが切るメッセージの上限（文字数）。 */
const LOG_MESSAGE_LIMIT = 1000

/** ピーク値などの数値。小数 1 桁までで、末尾の 0 は書かない（92.5 / 95）。 */
function formatPct(value: number): string {
  return `${Number(value.toFixed(1))}%`
}

/** `ref` の構造化した値があるか（古いサーバ・追加前のバックエンドの応答には無い）。 */
function hasStructuredMetric(item: TimelineViewItem): boolean {
  return item.kind === 'metric' && item.ref.peak_value != null
}

/** 「ピーク 92.5%（時刻）」。時刻は設定のタイムゾーンで書く。 */
function peakText(item: TimelineViewItem, timeZone: string): string {
  const { peak_value, peak_at_utc } = item.ref
  if (peak_value == null) return ''
  const at = peak_at_utc ? `（${formatIsoInTimeZone(peak_at_utc, timeZone)}）` : ''
  return `ピーク ${formatPct(peak_value)}${at}`
}

/**
 * 区間の長さを文章で書く（記号の「～」に頼らず、スクリーンリーダーで「いつからいつまで」と読める）。
 * `end_utc` が無ければ単発。
 */
function IntervalText({ item, timeZone }: { item: TimelineViewItem; timeZone: string }) {
  const start = formatIsoInTimeZone(item.timestamp_utc, timeZone)
  const duration = intervalDurationMs(item)
  if (!item.end_utc || duration === null) {
    return <span className="timeline-row__interval">超過区間: {start}（単発）</span>
  }
  return (
    <span className="timeline-row__interval">
      超過区間: {start} から {formatIsoInTimeZone(item.end_utc, timeZone)} まで（継続 {formatDurationMs(duration)}）
    </span>
  )
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
  onOpenInMetrics,
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
  onOpenInMetrics: Props['onOpenInMetrics']
}) {
  const metricsFocus = onOpenInMetrics ? metricsFocusForItem(item) : null
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
        {item.kind === 'metric' ? (
          <>
            <IntervalText item={item} timeZone={timeZone} />
            {item.ref.continues_from_before ? (
              <span className="timeline-row__continues">期間の開始前から継続</span>
            ) : null}
            {hasStructuredMetric(item) ? (
              <span className="timeline-row__peak">
                {[
                  peakText(item, timeZone),
                  item.ref.threshold_pct != null ? `しきい値 ${formatPct(item.ref.threshold_pct)}` : '',
                  item.ref.sample_count != null ? `サンプル ${item.ref.sample_count} 件` : '',
                ]
                  .filter(Boolean)
                  .join('・')}
              </span>
            ) : item.detail ? (
              <span className="timeline-row__excerpt">{excerpt(item.detail)}</span>
            ) : null}
          </>
        ) : item.detail ? (
          <span className="timeline-row__excerpt">{excerpt(item.detail)}</span>
        ) : null}
      </button>
      {expanded ? (
        <div id={`${domId}-detail`} className="timeline-row__detail" role="region" aria-label={`${item.title} の詳細`}>
          <dl className="timeline-row__facts">
            {hasStructuredMetric(item) ? null : (
              <>
                <dt>メッセージ</dt>
                {item.kind === 'log' && item.detail?.trim() ? (
                  <dd className="timeline-row__message">
                    <pre className="timeline-row__log-message">{item.detail}</pre>
                    {item.detail.length >= LOG_MESSAGE_LIMIT && item.detail.endsWith('…') ? (
                      <span className="hint">
                        メッセージは {LOG_MESSAGE_LIMIT} 文字で切っています。全文はログのタブで確認してください。
                      </span>
                    ) : null}
                  </dd>
                ) : (
                  <dd className="timeline-row__message">{item.detail?.trim() ? item.detail : '—'}</dd>
                )}
              </>
            )}
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
            {item.kind === 'metric' || item.kind === 'log' ? null : (
              <>
                <dt>スコア</dt>
                <dd>{item.score != null ? <ScoreBadge score={item.score} /> : '—'}</dd>
              </>
            )}
            {item.kind === 'metric' ? (
              <>
                <dt>指標</dt>
                <dd>{item.ref.metric_key ?? '—'}</dd>
                <dt>超過区間</dt>
                <dd>
                  <IntervalText item={item} timeZone={timeZone} />
                </dd>
                {item.ref.threshold_pct != null ? (
                  <>
                    <dt>しきい値</dt>
                    <dd>{formatPct(item.ref.threshold_pct)}</dd>
                  </>
                ) : null}
                {item.ref.peak_value != null ? (
                  <>
                    <dt>ピーク</dt>
                    <dd>{peakText(item, timeZone).replace(/^ピーク /, '')}</dd>
                  </>
                ) : null}
                {item.ref.sample_count != null ? (
                  <>
                    <dt>サンプル数</dt>
                    <dd>{item.ref.sample_count} 件</dd>
                  </>
                ) : null}
              </>
            ) : null}
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
            {logsHref && item.kind !== 'metric' ? (
              <a className="btn btn--gray" href={logsHref}>
                ログで開く
              </a>
            ) : null}
            {metricsFocus ? (
              <button type="button" className="btn btn--gray" onClick={() => onOpenInMetrics?.(metricsFocus)}>
                グラフで開く
              </button>
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
  onOpenInMetrics,
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
          onOpenInMetrics={onOpenInMetrics}
        />
      ))}
    </ol>
  )
}
