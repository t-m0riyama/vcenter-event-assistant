/** 概要・イベント・グラフの自動更新 ON/OFF を保存する localStorage キー。 */
export const AUTO_REFRESH_ENABLED_STORAGE_KEY = 'vea.auto_refresh_enabled'

/** 自動更新の間隔（分）を保存する localStorage キー。 */
export const AUTO_REFRESH_INTERVAL_MINUTES_STORAGE_KEY = 'vea.auto_refresh_interval_minutes'

const DEFAULT_AUTO_REFRESH_ENABLED = true

const DEFAULT_AUTO_REFRESH_INTERVAL_MINUTES = 5

const MIN_INTERVAL_MINUTES = 1

const MAX_INTERVAL_MINUTES = 300

/**
 * 自動更新の間隔（分）を 1〜300 の整数に収める。
 */
export function clampAutoRefreshIntervalMinutes(n: number): number {
  return Math.min(MAX_INTERVAL_MINUTES, Math.max(MIN_INTERVAL_MINUTES, Math.trunc(n)))
}

/**
 * 保存済みの自動更新有効フラグを読む。未設定・不正な値のときはデフォルト（true）を返す。
 */
export function readStoredAutoRefreshEnabled(): boolean {
  if (typeof localStorage === 'undefined') {
    return DEFAULT_AUTO_REFRESH_ENABLED
  }
  const raw = localStorage.getItem(AUTO_REFRESH_ENABLED_STORAGE_KEY)
  if (raw === null) {
    return DEFAULT_AUTO_REFRESH_ENABLED
  }
  const lower = raw.trim().toLowerCase()
  if (lower === 'true' || lower === '1') return true
  if (lower === 'false' || lower === '0') return false
  return DEFAULT_AUTO_REFRESH_ENABLED
}

/**
 * 自動更新の有効／無効を保存する。
 */
export function writeStoredAutoRefreshEnabled(enabled: boolean): void {
  if (typeof localStorage === 'undefined') {
    return
  }
  localStorage.setItem(AUTO_REFRESH_ENABLED_STORAGE_KEY, enabled ? 'true' : 'false')
}

/**
 * 保存済みの間隔（分）を読む。未設定・不正な値のときはデフォルト（5）を返す。
 */
export function readStoredAutoRefreshIntervalMinutes(): number {
  if (typeof localStorage === 'undefined') {
    return DEFAULT_AUTO_REFRESH_INTERVAL_MINUTES
  }
  const raw = localStorage.getItem(AUTO_REFRESH_INTERVAL_MINUTES_STORAGE_KEY)
  if (raw === null) {
    return DEFAULT_AUTO_REFRESH_INTERVAL_MINUTES
  }
  const n = Number.parseInt(raw, 10)
  if (Number.isNaN(n)) {
    return DEFAULT_AUTO_REFRESH_INTERVAL_MINUTES
  }
  return clampAutoRefreshIntervalMinutes(n)
}

/**
 * 間隔（分）を保存する（1〜300 にクランプしてから書き込む）。
 */
export function writeStoredAutoRefreshIntervalMinutes(n: number): void {
  if (typeof localStorage === 'undefined') {
    return
  }
  const v = clampAutoRefreshIntervalMinutes(n)
  localStorage.setItem(AUTO_REFRESH_INTERVAL_MINUTES_STORAGE_KEY, String(v))
}
