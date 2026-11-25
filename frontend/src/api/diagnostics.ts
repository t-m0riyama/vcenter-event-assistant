import { apiDelete, apiGet, apiPost, apiPut } from '../api'
import {
  diagnosticCatalogSchema,
  diagnosticCandidateSchema,
  diagnosticOutputSchema,
  diagnosticPreviewSchema,
  diagnosticProcedureSchema,
  diagnosticRunSchema,
  type DiagnosticPreviewInput,
  diagnosticCommandSchema,
  diagnosticHostsSchema,
  diagnosticTargetSchema,
  diagnosticTargetsSchema,
  type DiagnosticCommandInput,
  type DiagnosticTargetInput,
} from './schemas/diagnostics'
import { vcenterSchema } from './schemas/vcenters'

const base = '/api/diagnostics'
export const diagnosticSSHPath = `${base}/ssh`

type Revisioned = { id: string; revision: string }

export async function listDiagnosticTargets(signal?: AbortSignal) {
  return diagnosticTargetsSchema.parse(await apiGet<unknown>(`${base}/targets`, signal))
}

export async function fetchDiagnosticTargets(signal?: AbortSignal) {
  const [targets, vcenters] = await Promise.all([
    listDiagnosticTargets(signal),
    apiGet<unknown>('/api/vcenters', signal),
  ])
  return { items: targets, vcenters: vcenterSchema.array().parse(vcenters) }
}

export async function fetchDiagnosticHosts(vcenterId: string, signal?: AbortSignal) {
  return diagnosticHostsSchema.parse(
    await apiGet<unknown>(`${base}/vcenters/${encodeURIComponent(vcenterId)}/hosts`, signal),
  )
}

export async function fetchDiagnosticCommands(signal?: AbortSignal) {
  const { custom, builtin, parameter_types } = diagnosticCatalogSchema.parse(
    await apiGet<unknown>(`${base}/commands`, signal),
  )
  return { items: custom, builtin, parameterTypes: parameter_types }
}

async function save(path: string, input: object, row: Revisioned | null) {
  if (!row) return apiPost<unknown>(path, input)
  return apiPut<unknown>(`${path}/${encodeURIComponent(row.id)}`, { ...input, revision: row.revision })
}

function remove(path: string, row: Revisioned) {
  const query = new URLSearchParams({ revision: row.revision })
  return apiDelete(`${path}/${encodeURIComponent(row.id)}?${query}`)
}

export const diagnosticTargetApi = {
  fetch: fetchDiagnosticTargets,
  save: async (input: DiagnosticTargetInput, row: Revisioned | null) =>
    diagnosticTargetSchema.parse(await save(`${base}/targets`, input, row)),
  remove: (row: Revisioned) => remove(`${base}/targets`, row),
}

export const diagnosticCommandApi = {
  fetch: fetchDiagnosticCommands,
  save: async (input: DiagnosticCommandInput, row: Revisioned | null) =>
    diagnosticCommandSchema.parse(await save(`${base}/commands`, input, row)),
  remove: (row: Revisioned) => remove(`${base}/commands`, row),
}

export async function fetchDiagnosticProcedures(signal?: AbortSignal) {
  return diagnosticProcedureSchema.array().parse(await apiGet<unknown>('/api/event-patterns/procedures', signal))
}

export async function fetchIncidentProcedures(id: string, signal?: AbortSignal) {
  return diagnosticCandidateSchema.array().parse(
    await apiGet<unknown>(`/api/incidents/${encodeURIComponent(id)}/procedures`, signal),
  )
}

export async function fetchDiagnosticOutput(id: string, runId: number, signal?: AbortSignal) {
  return diagnosticOutputSchema.parse(
    await apiGet<unknown>(`/api/incidents/${encodeURIComponent(id)}/diagnostic-runs/${runId}`, signal),
  )
}

function runsPath(id: string) {
  return `${base}/incidents/${encodeURIComponent(id)}/runs`
}

export async function previewDiagnosticRun(id: string, input: DiagnosticPreviewInput) {
  return diagnosticPreviewSchema.parse(await apiPost<unknown>(`${runsPath(id)}/preview`, input))
}

export async function executeDiagnosticRun(id: string, input: DiagnosticPreviewInput, fingerprint: string, signal: AbortSignal) {
  return diagnosticRunSchema.parse(await apiPost<unknown>(runsPath(id), { ...input, fingerprint }, undefined, signal))
}
