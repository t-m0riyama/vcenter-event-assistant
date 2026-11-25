import type { IncidentStatus } from '../../api/schemas/incidents'

export const INCIDENT_STATUS_LABELS: Record<IncidentStatus, string> = {
  open: '対応中',
  monitoring: '様子見',
  resolved: '解決',
}

export const INCIDENT_STATUS_BADGES: Record<IncidentStatus, string> = {
  open: 'badge badge--info',
  monitoring: 'badge badge--warning',
  resolved: 'badge',
}


// サーバーが記録する診断の実行者と同じ形式。
export function incidentActorName({ display_name: displayName, username }: { display_name?: string | null; username: string }) {
  const available = 256 - Array.from(username).length - 2
  return displayName && displayName !== username && available > 0
    ? `${Array.from(displayName).slice(0, available).join('')}（${username}）`
    : username
}
