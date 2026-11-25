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
