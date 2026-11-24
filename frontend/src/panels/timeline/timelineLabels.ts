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

export const CONFIG_CHANGE_LABELS: ReadonlyMap<string, string> = new Map([
  ['vm_reconfigure', 'VM の構成変更'],
  ['maintenance_enter', 'メンテナンスモードに入った'],
  ['maintenance_exit', 'メンテナンスモードを出た'],
  ['cluster_config', 'クラスタの設定の変更'],
  ['network_config', 'ネットワークの設定の変更'],
  ['storage_config', 'ストレージの設定の変更'],
  ['resource_config', 'リソースの割り当ての変更'],
  ['host_config', 'ホストの設定の変更'],
  ['host_access', 'ホストのアクセスの設定の変更'],
  ['permission', '権限とロールの変更'],
  ['inventory', 'インベントリの変更'],
  ['upgrade', 'アップグレード'],
])

/** 一覧の行に出すメッセージの抜粋。長いときは省略記号を付ける。 */
export function excerpt(text: string | null | undefined, max = 90): string {
  const flat = (text ?? '').replace(/\s+/g, ' ').trim()
  return flat.length > max ? `${flat.slice(0, max)}…` : flat
}

/** 割合（%）の書き方。小数は 2 桁まで、末尾の 0 は書かない（80 → 80%、82.5 → 82.5%、82.55 → 82.55%）。 */
export function formatPct(value: number): string {
  return `${Number(value.toFixed(2))}%`
}

/**
 * タイトルが対象名で始まるか（ログの行は「ホスト名 ログの種類」）。始まるときは、対象名と並べて出すと
 * ホスト名が重なる。
 */
export function titleStartsWithEntity(title: string, entityName: string | null | undefined): boolean {
  return Boolean(entityName) && title.startsWith(entityName!) && title.length > entityName!.length
}

/** 対象名と並べて出すときのタイトル。対象名で始まるなら、その部分（と区切りの空白）を除く。 */
export function titleBesideEntity(title: string, entityName: string | null | undefined): string {
  return titleStartsWithEntity(title, entityName) ? title.slice(entityName!.length).trim() || title : title
}
