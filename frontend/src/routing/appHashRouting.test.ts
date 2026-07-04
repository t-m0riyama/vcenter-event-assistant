import { describe, expect, it } from 'vitest'

import { buildAppHash, parseAppHash } from './appHashRouting'

describe('parseAppHash', () => {
  it('defaults to summary when hash is empty', () => {
    expect(parseAppHash('')).toEqual({ tab: 'summary', settingsSubTab: 'general' })
    expect(parseAppHash('#')).toEqual({ tab: 'summary', settingsSubTab: 'general' })
  })

  it('parses main tab paths', () => {
    expect(parseAppHash('#/events')).toEqual({ tab: 'events', settingsSubTab: 'general' })
    expect(parseAppHash('#/metrics')).toEqual({ tab: 'metrics', settingsSubTab: 'general' })
  })

  it('parses settings sub tab paths', () => {
    expect(parseAppHash('#/settings')).toEqual({ tab: 'settings', settingsSubTab: 'general' })
    expect(parseAppHash('#/settings/vcenters')).toEqual({
      tab: 'settings',
      settingsSubTab: 'vcenters',
    })
    expect(parseAppHash('#/settings/score_rules')).toEqual({
      tab: 'settings',
      settingsSubTab: 'score_rules',
    })
  })

  it('falls back for unknown paths', () => {
    expect(parseAppHash('#/unknown')).toEqual({ tab: 'summary', settingsSubTab: 'general' })
    expect(parseAppHash('#/settings/unknown')).toEqual({
      tab: 'settings',
      settingsSubTab: 'general',
    })
  })
})

describe('buildAppHash', () => {
  it('builds main and settings hashes', () => {
    expect(buildAppHash('events')).toBe('#/events')
    expect(buildAppHash('settings', 'alerts')).toBe('#/settings/alerts')
  })
})
