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
        revision: '81d535f3-9d2b-4050-a276-284566833a48',
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

it('障害パターンの設定を読み込み、パターン ID と再通知間隔の型を検証する', () => {
  const rule = {
    name: 'APD', rule_type: 'event_pattern', is_enabled: true, alert_level: 'error',
    config: { pattern_ids: ['apd-timeout'], cooldown_minutes: 10 },
  }
  const file = (config: unknown) => ({
    format: 'vea-alert-rules', version: 1, rules: [{ ...rule, config }],
  })
  expect(alertRulesFileSchema.parse(file(rule.config)).rules[0]).toEqual(rule)
  expect(alertRulesFileSchema.safeParse(file({ pattern_ids: 'apd-timeout' })).success).toBe(false)
  expect(alertRulesFileSchema.safeParse(file({ cooldown_minutes: 0 })).success).toBe(false)
})

it('インポートする障害パターン ID を初出順でまとめる', () => {
  const result = alertRulesFileSchema.parse({
    format: 'vea-alert-rules',
    version: 1,
    rules: [{
      name: '複数の障害パターン', rule_type: 'event_pattern', is_enabled: true, alert_level: 'error',
      config: { pattern_ids: ['ha-failover', 'apd-timeout', 'ha-failover'], cooldown_minutes: 10 },
    }],
  })
  expect(result.rules[0].config).toEqual({ pattern_ids: ['ha-failover', 'apd-timeout'], cooldown_minutes: 10 })
})
