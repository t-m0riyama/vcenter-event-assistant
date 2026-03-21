import { describe, expect, it } from 'vitest'

import { buildEventExportFilename, eventRowsToCsv, type EventCsvRow } from './eventCsv'

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
      'id,occurred_at,vcenter_name,event_type,severity,message,user_name,entity_name,entity_type,notable_score,notable_tags,user_comment\r\n',
    )
  })

  it('serializes one row', () => {
    const csv = eventRowsToCsv([base])
    expect(csv).toBe(
      'id,occurred_at,vcenter_name,event_type,severity,message,user_name,entity_name,entity_type,notable_score,notable_tags,user_comment\r\n' +
        '1,2024/1/1 9:00:00,lab-vc,VmPoweredOnEvent,info,hello,admin,vm-1,VirtualMachine,10,"[""a"",""b""]",\r\n',
    )
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
