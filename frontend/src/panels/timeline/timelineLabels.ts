import type { TimelineLevel, TimelineSource } from '../../api/schemas'

export const LEVEL_LABELS: Record<TimelineLevel, string> = {
  critical: 'クリティカル',
  error: 'エラー',
  warning: '警告',
  info: '情報',
}

/** レベルのバッジのクラス。色に加えて、文字（LEVEL_LABELS）でも伝える。 */
export const LEVEL_BADGE_CLASS: Record<TimelineLevel, string> = {
  critical: 'badge badge--error timeline-badge--critical',
  error: 'badge badge--error',
  warning: 'badge badge--warning',
  info: 'badge badge--info',
}

export const KIND_LABELS: Record<TimelineSource, string> = {
  event: 'イベント',
  alert: 'アラート',
  metric: 'メトリクス',
  log: 'ログ',
}

/** アラートの状態の表記（通知履歴タブと同じ言い回し）。 */
export function alertStateLabel(state: string | null | undefined): string {
  if (!state) return '—'
  if (state === 'firing') return '発火中'
  if (state === 'stale') return 'データ古い'
  return '回復済み'
}

/** 一覧の行に出すメッセージの抜粋。長いときは省略記号を付ける。 */
export function excerpt(text: string | null | undefined, max = 90): string {
  const flat = (text ?? '').replace(/\s+/g, ' ').trim()
  return flat.length > max ? `${flat.slice(0, max)}…` : flat
}
