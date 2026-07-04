import type { EventRow } from '../api/schemas'
import { normalizeEventListPayload } from '../api/schemas'
import {
  buildEventListSearchParams,
  type EventListFilterFields,
  type EventListUtcRange,
} from './buildEventListQuery'
import { EVENT_EXPORT_CHUNK } from './constants'

export type FetchEventsPage = (searchParams: URLSearchParams) => Promise<unknown>

/**
 * 現在のフィルタ・期間に一致するイベントを CSV 出力用に全件取得する（ページング）。
 */
export async function fetchAllEventsForExport(
  fetchPage: FetchEventsPage,
  filters: EventListFilterFields,
  range: EventListUtcRange,
  chunkSize: number = EVENT_EXPORT_CHUNK,
): Promise<EventRow[]> {
  const all: EventRow[] = []
  let offset = 0
  let totalExpected = 0

  for (;;) {
    const q = buildEventListSearchParams({
      limit: chunkSize,
      offset,
      filters,
      range,
    })
    const raw = await fetchPage(q)
    const { items, total, rawItemCount } = normalizeEventListPayload(raw)
    totalExpected = total
    all.push(...items)
    offset += rawItemCount
    if (rawItemCount === 0) break
    if (all.length >= totalExpected) break
  }

  return all
}
