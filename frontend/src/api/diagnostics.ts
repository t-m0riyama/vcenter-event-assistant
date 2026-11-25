import { apiDelete, apiGet, apiPost, apiPut } from '../api'
import {
  diagnosticCatalogSchema,
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

export async function fetchDiagnosticTargets(signal?: AbortSignal) {
  const [targets, vcenters] = await Promise.all([
    apiGet<unknown>(`${base}/targets`, signal),
    apiGet<unknown>('/api/vcenters', signal),
  ])
  return { items: diagnosticTargetsSchema.parse(targets), vcenters: vcenterSchema.array().parse(vcenters) }
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
