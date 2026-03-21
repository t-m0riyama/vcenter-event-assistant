import { formatIsoInTimeZone } from '../datetime/formatIsoInTimeZone'
import type { EventRow } from '../api/schemas'
import type { EventCsvRow } from './eventCsv'

export function eventRowToCsvRow(
  e: EventRow,
  vcenterName: string,
  timeZone: string,
): EventCsvRow {
  return {
    id: e.id,
    occurred_at: formatIsoInTimeZone(e.occurred_at, timeZone),
    vcenter_name: vcenterName,
    event_type: e.event_type,
    message: e.message,
    severity: e.severity,
    user_name: e.user_name ?? null,
    entity_name: e.entity_name ?? null,
    entity_type: e.entity_type ?? null,
    notable_score: e.notable_score,
    notable_tags: e.notable_tags as unknown[] | null,
    user_comment: e.user_comment ?? null,
  }
}
