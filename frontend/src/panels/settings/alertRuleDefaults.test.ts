import { describe, expect, it } from 'vitest'
import { DEFAULT_ALERT_METRIC_KEY } from './alertRuleDefaults'

describe('alertRuleDefaults', () => {
  it('DEFAULT_ALERT_METRIC_KEY matches collector CPU key', () => {
    expect(DEFAULT_ALERT_METRIC_KEY).toBe('host.cpu.usage_pct')
  })
})
