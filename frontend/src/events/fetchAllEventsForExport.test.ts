import { describe, expect, it, vi } from 'vitest'

import type { EventRow } from '../api/schemas'
import { fetchAllEventsForExport } from './fetchAllEventsForExport'

function makeEvent(id: number): EventRow {
  return {
    id,
    vcenter_id: 'vc-1',
    occurred_at: `2026-03-22T10:00:0${id}Z`,
    event_type: 'VmPoweredOnEvent',
    message: 'm',
    severity: 'info',
    user_name: null,
    entity_name: null,
    entity_type: null,
    notable_score: 1,
    notable_tags: null,
    user_comment: null,
    type_guide: null,
  }
}

describe('fetchAllEventsForExport', () => {
  it('total 件数まで chunk 取得を繰り返す', async () => {
    const fetchPage = vi
      .fn()
      .mockResolvedValueOnce({ items: [makeEvent(1), makeEvent(2)], total: 3 })
      .mockResolvedValueOnce({ items: [makeEvent(3)], total: 3 })

    const rows = await fetchAllEventsForExport(
      fetchPage,
      {
        minScore: '',
        filterEventType: '',
        filterSeverity: '',
        filterMessage: '',
        filterComment: '',
      },
      { from: '2026-03-22T00:00:00Z', to: '2026-03-23T00:00:00Z' },
      2,
    )

    expect(rows).toHaveLength(3)
    expect(fetchPage).toHaveBeenCalledTimes(2)
    const firstParams = fetchPage.mock.calls[0][0] as URLSearchParams
    expect(firstParams.get('limit')).toBe('2')
    expect(firstParams.get('offset')).toBe('0')
    const secondParams = fetchPage.mock.calls[1][0] as URLSearchParams
    expect(secondParams.get('offset')).toBe('2')
  })

  it('空ページで打ち切る', async () => {
    const fetchPage = vi.fn().mockResolvedValueOnce({ items: [], total: 0 })
    const rows = await fetchAllEventsForExport(
      fetchPage,
      {
        minScore: '',
        filterEventType: '',
        filterSeverity: '',
        filterMessage: '',
        filterComment: '',
      },
      {},
      100,
    )
    expect(rows).toEqual([])
    expect(fetchPage).toHaveBeenCalledTimes(1)
  })
})
