import { apiGet } from '../api'
import {
  inventoryConfigDiffResponseSchema,
  inventoryImpactResponseSchema,
  inventoryStatusResponseSchema,
  type InventoryConfigDiffResponse,
  type InventoryImpactResponse,
  type InventoryStatusResponse,
} from './schemas'

export async function getInventoryImpact(query: {
  vcenter_id: string
  entity_moid: string
  at: string
  from: string
  to: string
}, signal?: AbortSignal): Promise<InventoryImpactResponse> {
  const raw = await apiGet<unknown>(`/api/inventory/impact?${new URLSearchParams(query)}`, signal)
  return inventoryImpactResponseSchema.parse(raw)
}

export type InventoryConfigDiffQuery = {
  vcenter_id: string
  entity_moid: string
  from: string
  to: string
}

export async function getInventoryConfigDiffs(
  query: InventoryConfigDiffQuery, signal?: AbortSignal,
): Promise<InventoryConfigDiffResponse> {
  const raw = await apiGet<unknown>(`/api/inventory/config-diffs?${new URLSearchParams(query)}`, signal)
  return inventoryConfigDiffResponseSchema.parse(raw)
}

export async function getInventoryStatus(): Promise<InventoryStatusResponse> {
  const raw = await apiGet<unknown>('/api/inventory/status')
  return inventoryStatusResponseSchema.parse(raw)
}
