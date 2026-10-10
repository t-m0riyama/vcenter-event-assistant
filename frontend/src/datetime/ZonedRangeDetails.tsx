import type { ReactNode } from 'react'
import { ZonedRangeFields, type ZonedRangeParts } from './ZonedRangeFields'

type ZonedRangeDetailsProps = {
  /** 折りたたんだときに見出しの横に出す、今の期間の要約。 */
  displayLabel: string
  hint: ReactNode
  value: ZonedRangeParts
  onChange: (next: ZonedRangeParts) => void
  onQuickPreset?: (durationMs: number) => void
  className?: string
  /** 説明と入力欄のあいだに置くもの（グラフの自動更新など）。 */
  children?: ReactNode
}

/** 折りたためる「表示期間」（グラフ・チャット・タイムラインで共通）。 */
export function ZonedRangeDetails({
  displayLabel,
  hint,
  value,
  onChange,
  onQuickPreset,
  className,
  children,
}: ZonedRangeDetailsProps) {
  return (
    <details className={className ? `toolbar__filters-details ${className}` : 'toolbar__filters-details'}>
      <summary className="toolbar__filters-summary">
        <span className="toolbar__filters-summary__title">表示期間</span>
        <span className="toolbar__filters-summary__preview">{displayLabel}</span>
      </summary>
      <p className="hint toolbar__filters-hint">{hint}</p>
      {children}
      <ZonedRangeFields value={value} onChange={onChange} onQuickPreset={onQuickPreset} />
    </details>
  )
}
