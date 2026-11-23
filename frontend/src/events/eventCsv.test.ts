import { describe, expect, it } from 'vitest'

import { eventRowSchema } from '../api/schemas/events'
import { buildEventExportFilename, eventRowsToCsv, type EventCsvRow } from './eventCsv'
import { eventRowToCsvRow } from './eventRowToCsv'

const base: EventCsvRow = {
  id: 1,
  occurred_at: '2024/1/1 9:00:00',
  vcenter_name: 'lab-vc',
  event_type: 'VmPoweredOnEvent',
  message: 'hello',
  severity: 'info',
  user_name: 'admin',
  entity_name: 'vm-1',
  entity_type: 'VirtualMachine',
  notable_score: 10,
  notable_tags: ['a', 'b'],
  user_comment: null,
}

describe('eventRowsToCsv', () => {
  it('outputs header and CRLF line endings', () => {
    const csv = eventRowsToCsv([])
    expect(csv).toBe(
      'id,occurred_at,vcenter_name,event_type,severity,message,user_name,entity_name,entity_type,entity_moid,notable_score,notable_tags,user_comment\r\n',
    )
  })

  it('serializes one row', () => {
    const csv = eventRowsToCsv([base])
    expect(csv).toBe(
      'id,occurred_at,vcenter_name,event_type,severity,message,user_name,entity_name,entity_type,entity_moid,notable_score,notable_tags,user_comment\r\n' +
        '1,2024/1/1 9:00:00,lab-vc,VmPoweredOnEvent,info,hello,admin,vm-1,VirtualMachine,,10,"[""a"",""b""]",\r\n',
    )
  })

  it.each([
    ['vm-101', ',VirtualMachine,vm-101,10,'],
    ['vm-101,102', ',VirtualMachine,"vm-101,102",10,'],
    [null, ',VirtualMachine,,10,'],
    [undefined, ',VirtualMachine,,10,'],
  ])('exports entity_moid %s from an API row', (moid, expected) => {
    const event = eventRowSchema.parse({
      ...base,
      vcenter_id: 'vc-1',
      occurred_at: '2024-01-01T00:00:00Z',
      ...(moid === undefined ? {} : { entity_moid: moid }),
    })
    const csv = eventRowsToCsv([eventRowToCsvRow(event, 'lab-vc', 'Asia/Tokyo')])
    expect(csv).toContain(expected)
  })

  it('escapes message and user_comment with special chars', () => {
    const csv = eventRowsToCsv([
      {
        ...base,
        message: 'say "hi", world',
        user_comment: 'line1\nline2',
      },
    ])
    expect(csv).toContain('"say ""hi"", world"')
    expect(csv).toContain('"line1\nline2"')
  })

  it('neutralizes formula-like text but not numeric columns', () => {
    const csv = eventRowsToCsv([
      {
        ...base,
        user_name: '=HYPERLINK("http://evil.example/")',
        entity_name: '@SUM(A1)',
        message: '-cmd',
        notable_score: -5,
      },
    ])
    expect(csv).toContain(`,"'=HYPERLINK(""http://evil.example/"")",'@SUM(A1),`)
    expect(csv).toContain(",'-cmd,")
    expect(csv).toContain(',-5,')
  })

  it('uses empty notable_tags when null', () => {
    const csv = eventRowsToCsv([{ ...base, notable_tags: null }])
    expect(csv).toMatch(/,10,,\r\n$/)
  })
})

describe('buildEventExportFilename', () => {
  it('uses events prefix and csv extension', () => {
    const s = buildEventExportFilename(new Date(2025, 5, 15, 14, 30, 7))
    expect(s).toBe('events-20250615-143007.csv')
  })
})
