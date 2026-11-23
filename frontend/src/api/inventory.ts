import { apiGet } from '../api'
import {
  inventoryImpactResponseSchema,
  inventoryStatusResponseSchema,
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

export async function getInventoryStatus(): Promise<InventoryStatusResponse> {
  const raw = await apiGet<unknown>('/api/inventory/status')
  return inventoryStatusResponseSchema.parse(raw)
}
