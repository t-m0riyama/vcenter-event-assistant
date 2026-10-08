import type { Role } from '../api/schemas'

const RANK: Record<Role, number> = { viewer: 0, operator: 1, admin: 2 }

/** ``actual`` が ``required`` 以上のロールか（サーバの role_at_least と同じ順序）。 */
export function roleAtLeast(actual: Role, required: Role): boolean {
  return RANK[actual] >= RANK[required]
}

export const ROLE_LABELS: Record<Role, string> = {
  admin: '管理者',
  operator: 'オペレーター',
  viewer: '閲覧者',
}
