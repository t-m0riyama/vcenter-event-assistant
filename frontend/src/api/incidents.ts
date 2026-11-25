import { apiDelete, apiGet, apiPatch, apiPost } from '../api'
import {
  incidentCreateResponseSchema, incidentCreateSchema, incidentDetailSchema, incidentEntryCreateSchema,
  incidentEntrySchema, incidentLinkResponseSchema, incidentListSchema, incidentPatchSchema,
  incidentSnapshotLinksRequestSchema, incidentTimedLinksRequestSchema,
  type IncidentCreate, type IncidentPatch, type IncidentStatus, type TimedIncidentSource,
} from './schemas/incidents'

const path = '/api/incidents'
const detailPath = (id: string) => `${path}/${encodeURIComponent(id)}`

export const INCIDENT_PAGE_SIZE = 50

export async function listIncidents(options: {
  statuses?: readonly IncidentStatus[]
  query?: string
  offset?: number
  signal?: AbortSignal
}) {
  const query = new URLSearchParams({ limit: String(INCIDENT_PAGE_SIZE), offset: String(options.offset ?? 0) })
  for (const status of options.statuses ?? []) query.append('status', status)
  if (options.query) query.set('q', options.query)
  return incidentListSchema.parse(await apiGet<unknown>(`${path}?${query}`, options.signal))
}

export async function getIncident(id: string, signal?: AbortSignal) {
  return incidentDetailSchema.parse(await apiGet<unknown>(detailPath(id), signal))
}

export async function createIncident(body: IncidentCreate) {
  return incidentCreateResponseSchema.parse(await apiPost<unknown>(path, incidentCreateSchema.parse(body)))
}

export async function patchIncident(id: string, body: IncidentPatch) {
  return incidentDetailSchema.parse(await apiPatch<unknown>(detailPath(id), incidentPatchSchema.parse(body)))
}

export async function addIncidentEntry(id: string, body: string) {
  return incidentEntrySchema.parse(await apiPost<unknown>(`${detailPath(id)}/entries`, incidentEntryCreateSchema.parse({ body })))
}

export type IncidentLinkSource =
  | { kind: 'events' | 'alerts'; items: TimedIncidentSource[] }
  | { kind: 'snapshots'; ids: string[] }

export async function addIncidentLinks(id: string, source: IncidentLinkSource) {
  const body = source.kind === 'snapshots'
    ? incidentSnapshotLinksRequestSchema.parse({ snapshot_ids: source.ids })
    : incidentTimedLinksRequestSchema.parse({ items: source.items })
  return incidentLinkResponseSchema.parse(await apiPost<unknown>(`${detailPath(id)}/${source.kind}`, body))
}

export function deleteIncident(id: string, kind?: 'entries' | IncidentLinkSource['kind'], rowId?: number) {
  return apiDelete(kind === undefined ? detailPath(id) : `${detailPath(id)}/${kind}/${rowId}`)
}
