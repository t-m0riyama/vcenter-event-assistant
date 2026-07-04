import type { MainTabId } from '../components/main-tab-icons'
import type { SettingsSubTabId } from '../components/settings-subtab-icons'

export const MAIN_TAB_IDS: readonly MainTabId[] = [
  'summary',
  'events',
  'metrics',
  'digests',
  'alerts',
  'chat',
  'timeline',
  'settings',
] as const

export const SETTINGS_SUB_TAB_IDS: readonly SettingsSubTabId[] = [
  'general',
  'vcenters',
  'score_rules',
  'event_type_guides',
  'alerts',
  'chat_samples',
] as const

const MAIN_TAB_SET = new Set<string>(MAIN_TAB_IDS)
const SETTINGS_SUB_TAB_SET = new Set<string>(SETTINGS_SUB_TAB_IDS)

export type ParsedAppHash = {
  readonly tab: MainTabId
  readonly settingsSubTab: SettingsSubTabId
}

function isMainTabId(value: string): value is MainTabId {
  return MAIN_TAB_SET.has(value)
}

function isSettingsSubTabId(value: string): value is SettingsSubTabId {
  return SETTINGS_SUB_TAB_SET.has(value)
}

/**
 * `#/events` や `#/settings/score_rules` 形式のハッシュをタブ状態へ解釈する。
 * 無効・空のときは概要タブへフォールバックする。
 */
export function parseAppHash(hash: string): ParsedAppHash {
  const raw = hash.replace(/^#/, '').replace(/^\//, '')
  const segments = raw.split('/').filter(Boolean)

  if (segments.length === 0) {
    return { tab: 'summary', settingsSubTab: 'general' }
  }

  const first = segments[0]
  if (!isMainTabId(first)) {
    return { tab: 'summary', settingsSubTab: 'general' }
  }

  if (first === 'settings') {
    const sub = segments[1]
    if (sub && isSettingsSubTabId(sub)) {
      return { tab: 'settings', settingsSubTab: sub }
    }
    return { tab: 'settings', settingsSubTab: 'general' }
  }

  return { tab: first, settingsSubTab: 'general' }
}

/** 現在のタブ状態から共有・リロード可能なハッシュ文字列を組み立てる。 */
export function buildAppHash(tab: MainTabId, settingsSubTab: SettingsSubTabId = 'general'): string {
  if (tab === 'settings') {
    return `#/settings/${settingsSubTab}`
  }
  return `#/${tab}`
}

/** ブラウザ URL のハッシュを更新する（履歴は replace）。 */
export function replaceAppHash(tab: MainTabId, settingsSubTab: SettingsSubTabId = 'general'): void {
  const nextHash = buildAppHash(tab, settingsSubTab)
  const { pathname, search, hash } = window.location
  if (hash === nextHash) {
    return
  }
  window.history.replaceState(null, '', `${pathname}${search}${nextHash}`)
}
