import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  buildEventTypeGuidesExportPayload,
  eventTypeGuidesFileSchema,
} from './schemas'

const here = dirname(fileURLToPath(import.meta.url))

describe('eventTypeGuidesFileSchema', () => {
  it('accepts valid export shape', () => {
    const raw = {
      format: 'vea-event-type-guides',
      version: 1,
      exportedAt: '2026-03-22T00:00:00.000Z',
      guides: [
        {
          event_type: 'vim.event.A',
          general_meaning: 'm',
          typical_causes: null,
          remediation: null,
          action_required: false,
        },
      ],
    }
    expect(eventTypeGuidesFileSchema.parse(raw).guides[0].event_type).toBe('vim.event.A')
  })

  it('rejects duplicate event_type in guides', () => {
    const raw = {
      format: 'vea-event-type-guides',
      version: 1,
      guides: [
        { event_type: 'vim.event.A', action_required: false },
        { event_type: 'vim.event.A', action_required: true },
      ],
    }
    expect(() => eventTypeGuidesFileSchema.parse(raw)).toThrow()
  })
})

describe('data/seed/event-type-guides-priority-v1.json', () => {
  it('parses with eventTypeGuidesFileSchema', () => {
    const path = join(here, '../../../data/seed/event-type-guides-priority-v1.json')
    const raw: unknown = JSON.parse(readFileSync(path, 'utf-8'))
    const parsed = eventTypeGuidesFileSchema.parse(raw)
    expect(parsed.format).toBe('vea-event-type-guides')
    expect(parsed.version).toBe(1)
    expect(parsed.guides.length).toBeGreaterThan(0)
  })
})

describe('buildEventTypeGuidesExportPayload', () => {
  it('builds validated file payload', () => {
    const p = buildEventTypeGuidesExportPayload([
      {
        id: 1,
        event_type: 'vim.event.X',
        general_meaning: 'g',
        typical_causes: null,
        remediation: undefined,
        action_required: true,
      },
    ])
    expect(p.format).toBe('vea-event-type-guides')
    expect(p.guides).toEqual([
      {
        event_type: 'vim.event.X',
        general_meaning: 'g',
        typical_causes: null,
        remediation: null,
        action_required: true,
      },
    ])
  })
})
