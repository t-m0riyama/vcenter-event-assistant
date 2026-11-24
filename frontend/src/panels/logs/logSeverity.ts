// バックエンドの services/log_patterns/severity.py の集計用ランクに対応する。
const SEVERITY_NAMES: readonly string[] = ['debug', 'info', 'warning', 'error', 'critical']

export function logSeverityForRank(rank: number): string | undefined {
  return SEVERITY_NAMES[rank]
}
