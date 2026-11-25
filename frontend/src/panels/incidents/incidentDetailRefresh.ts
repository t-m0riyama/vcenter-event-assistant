import type { IncidentDetail } from '../../api/schemas/incidents'

/**
 * 編集の下書きがあるときに読み直した詳細を当てる。紐付け・経過・診断の結果だけを最新にし、件名などの項目と revision は元のまま残す。
 *
 * 最新の revision を黙って使うと、下書きの保存がほかの人の変更を 409 なしで上書きしてしまう。
 * 古い revision のまま保存すれば、ほかの人が変えていたときは 409（`incident_stale`）になり、利用者が読み直して見比べられる。
 */
export function keepEditedFields(current: IncidentDetail, fresh: IncidentDetail): IncidentDetail {
  return { ...current, entries: fresh.entries, events: fresh.events, alerts: fresh.alerts, snapshots: fresh.snapshots, diagnostic_runs: fresh.diagnostic_runs }
}
