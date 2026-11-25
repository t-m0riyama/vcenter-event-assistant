import { describe, expect, it } from 'vitest'
import { AT, INCIDENT_DETAIL, INCIDENT_ID, INCIDENT_LIST, SNAPSHOT_ID } from '../../test/incidentFixtures'
import {
  incidentCreateResponseSchema, incidentCreateSchema, incidentDetailSchema, incidentEntryCreateSchema,
  incidentLinkResponseSchema, incidentListSchema, incidentPatchSchema, incidentSnapshotLinksRequestSchema,
  incidentTimedLinksRequestSchema, timedIncidentSourceSchema,
} from './incidents'

describe('インシデント API のスキーマ', () => {
  it('一覧・詳細・作成と ID ごとの結果を読む', () => {
    expect(incidentListSchema.parse(INCIDENT_LIST).items[0].snapshot_count).toBe(1)
    expect(incidentDetailSchema.parse(INCIDENT_DETAIL)).toEqual(INCIDENT_DETAIL)
    expect(incidentDetailSchema.safeParse({ ...INCIDENT_DETAIL, alerts: [{ ...INCIDENT_DETAIL.alerts[0], source_exists: undefined }] }).success).toBe(false)
    const events = [{ id: 123, result: 'added', link_id: 1 }, { id: 124, result: 'not_found' }]
    expect(incidentLinkResponseSchema.parse({ results: events, added: 1 }).results).toEqual(events)
    const snapshots = [{ id: SNAPSHOT_ID, result: 'no_result' }]
    expect(incidentCreateResponseSchema.parse({
      incident: INCIDENT_DETAIL, link_results: { events, alerts: [], snapshots },
    }).link_results.snapshots).toEqual(snapshots)
  })

  it('時刻を変換せず、時刻か範囲の両端を要求する', () => {
    expect(timedIncidentSourceSchema.parse({ id: 1, occurred_at: AT }).occurred_at).toBe(AT)
    expect(timedIncidentSourceSchema.safeParse({ id: 1, occurred_from: AT, occurred_to: AT }).success).toBe(true)
    expect(timedIncidentSourceSchema.safeParse({ id: 1, occurred_to: AT }).success).toBe(false)
    expect(incidentTimedLinksRequestSchema.safeParse({ items: Array(101).fill({ id: 1, occurred_at: AT }) }).success).toBe(false)
    expect(incidentSnapshotLinksRequestSchema.safeParse({ snapshot_ids: ['bad-id'] }).success).toBe(false)
  })

  it('PATCH の省略と null、件名とメモの制約を扱う', () => {
    expect(incidentPatchSchema.parse({ revision: INCIDENT_ID, assignee: null })).toEqual({ revision: INCIDENT_ID, assignee: null })
    expect(incidentPatchSchema.safeParse({ revision: INCIDENT_ID, status: null }).success).toBe(false)
    expect(incidentPatchSchema.safeParse({ revision: INCIDENT_ID, title: null }).success).toBe(false)
    expect(incidentCreateSchema.safeParse({ title: '  ' }).success).toBe(false)
    expect(incidentEntryCreateSchema.safeParse({ body: 'あ'.repeat(4001) }).success).toBe(false)
  })
})
