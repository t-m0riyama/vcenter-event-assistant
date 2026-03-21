import { apiGet } from '../api'
import { asArray } from '../utils/asArray'
import { mergeMetricKeyOptions } from './knownMetricKeys'

/**
 * `GET /api/metrics/keys` の結果をカタログとマージしたキー一覧を返す。
 */
export async function fetchMetricKeysForVcenter(vcenterId: string): Promise<string[]> {
  const q = vcenterId ? `?vcenter_id=${encodeURIComponent(vcenterId)}` : ''
  const data = await apiGet<{ metric_keys?: unknown }>(`/api/metrics/keys${q}`)
  return mergeMetricKeyOptions(asArray<string>(data.metric_keys))
}

/**
 * 取得後も有効なら前回選択を維持し、なければ先頭（または空文字）。
 */
export function pickMetricKeyAfterFetch(previous: string, keys: string[]): string {
  return keys.includes(previous) ? previous : (keys[0] ?? '')
}
