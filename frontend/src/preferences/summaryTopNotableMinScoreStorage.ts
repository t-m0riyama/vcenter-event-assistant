/** 概要の「要注意イベント（上位）」一覧の notable_score 下限（0〜100）を保存する localStorage キー。 */
export const SUMMARY_TOP_NOTABLE_MIN_SCORE_STORAGE_KEY = 'vea.summary_top_notable_min_score'

const DEFAULT_SUMMARY_TOP_NOTABLE_MIN_SCORE = 1

/**
 * 概要の要注意イベント絞り込みに使う値を、0〜100 の整数に収める。
 */
export function clampSummaryTopNotableMinScore(n: number): number {
  return Math.min(100, Math.max(0, Math.trunc(n)))
}

/**
 * 保存済みの下限を読む。未設定・不正な値のときはデフォルト（1）を返す。
 */
export function readStoredSummaryTopNotableMinScore(): number {
  if (typeof localStorage === 'undefined') {
    return DEFAULT_SUMMARY_TOP_NOTABLE_MIN_SCORE
  }
  const raw = localStorage.getItem(SUMMARY_TOP_NOTABLE_MIN_SCORE_STORAGE_KEY)
  if (raw === null) {
    return DEFAULT_SUMMARY_TOP_NOTABLE_MIN_SCORE
  }
  const n = Number.parseInt(raw, 10)
  if (Number.isNaN(n)) {
    return DEFAULT_SUMMARY_TOP_NOTABLE_MIN_SCORE
  }
  return clampSummaryTopNotableMinScore(n)
}

/**
 * 下限を保存する（0〜100 にクランプしてから書き込む）。
 */
export function writeStoredSummaryTopNotableMinScore(n: number): void {
  if (typeof localStorage === 'undefined') {
    return
  }
  const v = clampSummaryTopNotableMinScore(n)
  localStorage.setItem(SUMMARY_TOP_NOTABLE_MIN_SCORE_STORAGE_KEY, String(v))
}
