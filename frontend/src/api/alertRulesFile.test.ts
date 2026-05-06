import { describe, expect, it } from 'vitest'
import {
  alertRulesFileSchema,
  buildAlertRulesExportPayload,
} from './schemas'

describe('alertRulesFileSchema', () => {
  it('accepts valid export shape', () => {
    const raw = {
      format: 'vea-alert-rules',
      version: 1,
      exportedAt: '2026-05-06T00:00:00.000Z',
      rules: [
        {
          name: 'High CPU',
          rule_type: 'metric_threshold',
          is_enabled: true,
          alert_level: 'warning',
          config: { metric_key: 'cpu.usage.average', threshold: 90 },
        },
      ],
    }
    expect(alertRulesFileSchema.parse(raw).rules[0].name).toBe('High CPU')
  })

  it('rejects duplicate name in rules', () => {
    const raw = {
      format: 'vea-alert-rules',
      version: 1,
      rules: [
        {
          name: 'Dup Rule',
          rule_type: 'event_score',
          is_enabled: true,
          alert_level: 'warning',
          config: { threshold: 10, cooldown_minutes: 10 },
        },
        {
          name: 'Dup Rule',
          rule_type: 'metric_threshold',
          is_enabled: false,
          alert_level: 'error',
          config: { metric_key: 'mem.usage.average', threshold: 95 },
        },
      ],
    }
    expect(() => alertRulesFileSchema.parse(raw)).toThrow()
  })
})

describe('buildAlertRulesExportPayload', () => {
  it('builds validated file payload', () => {
    const payload = buildAlertRulesExportPayload([
      {
        id: 1,
        name: 'Score Alert',
        rule_type: 'event_score',
        is_enabled: true,
        alert_level: 'critical',
        config: { threshold: 70, cooldown_minutes: 5 },
        created_at: '2026-05-06T00:00:00Z',
      },
    ])
    expect(payload.format).toBe('vea-alert-rules')
    expect(payload.rules).toEqual([
      {
        name: 'Score Alert',
        rule_type: 'event_score',
        is_enabled: true,
        alert_level: 'critical',
        config: { threshold: 70, cooldown_minutes: 5 },
      },
    ])
  })
})
