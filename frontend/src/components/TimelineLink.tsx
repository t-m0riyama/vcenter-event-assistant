import { timelineEntryHash, type TimelineEntryInput } from '../routing/timelineHash'

type Props = TimelineEntryInput & {
  /** どの行のリンクか分かる名前（対象名や時刻を含める）。 */
  readonly ariaLabel?: string
}

/**
 * 「タイムラインで見る」リンク。起点の前後・vCenter・対象の条件で開く。
 * 時刻が読めないときは何も描画しない。
 */
export function TimelineLink({ ariaLabel, ...entry }: Props) {
  const href = timelineEntryHash(entry)
  if (!href) return null
  return (
    <a className="timeline-link" href={href} aria-label={ariaLabel}>
      タイムラインで見る
    </a>
  )
}
