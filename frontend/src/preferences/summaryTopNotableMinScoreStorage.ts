/** localStorage key for minimum notable score on the dashboard summary list (0–100). */
export const SUMMARY_TOP_NOTABLE_MIN_SCORE_STORAGE_KEY = 'vea.summary_top_notable_min_score'

const DEFAULT_SUMMARY_TOP_NOTABLE_MIN_SCORE = 1

/**
 * Clamps a value to the allowed range for summary top-notable filtering.
 */
export function clampSummaryTopNotableMinScore(n: number): number {
  return Math.min(100, Math.max(0, Math.trunc(n)))
}

/**
 * Reads the stored minimum score, or the default when missing or invalid.
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
 * Persists the minimum score (clamped to 0–100).
 */
export function writeStoredSummaryTopNotableMinScore(n: number): void {
  if (typeof localStorage === 'undefined') {
    return
  }
  const v = clampSummaryTopNotableMinScore(n)
  localStorage.setItem(SUMMARY_TOP_NOTABLE_MIN_SCORE_STORAGE_KEY, String(v))
}
