/** 重大度・スコアを一目で判別できるようにする共通バッジ。配色は styles/badges.css。 */

const SEVERITY_BADGE_CLASS: Record<string, string> = {
  info: 'badge--info',
  warning: 'badge--warning',
  error: 'badge--error',
}

/** 重大度バッジ。未知の値はニュートラル配色、未設定は「—」を表示する。 */
export function SeverityBadge({ severity }: { severity: string | null | undefined }) {
  const value = severity?.trim()
  if (!value) return <>—</>
  const cls = SEVERITY_BADGE_CLASS[value.toLowerCase()]
  return <span className={cls ? `badge ${cls}` : 'badge'}>{value}</span>
}

/** スコアバッジ。40 は要注意の既定しきい値（概要タブの表記と揃える）、70 以上を高危険とする。 */
export function ScoreBadge({ score }: { score: number }) {
  const cls =
    score >= 70 ? 'score-badge score-badge--high'
    : score >= 40 ? 'score-badge score-badge--elevated'
    : 'score-badge'
  return <span className={cls}>{score}</span>
}
