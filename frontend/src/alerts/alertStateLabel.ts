/** アラートの状態の表記。通知履歴とタイムラインで同じ言い回しを使う。状態が無いときは「—」。 */
export function alertStateLabel(state: string | null | undefined): string {
  if (!state) return '—'
  if (state === 'firing') return '発火中'
  if (state === 'stale') return 'データ古い'
  return '回復済み'
}
