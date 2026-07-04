import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import type { MainTabId } from '../components/main-tab-icons'
import { MAIN_TAB_IDS, SETTINGS_SUB_TAB_IDS } from '../routing/appHashRouting'
import {
  MAIN_TAB_HELP,
  SETTINGS_SUB_TAB_HELP,
  resolveTabHelp,
} from './tabHelpContent'

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')

function tabHelpMarker(markerId: string): string {
  return `<!-- vea-tab-help: ${markerId} -->`
}

function assertGuideDoc(entry: { userGuideDoc?: string; markerId?: string }, label: string) {
  if (!entry.userGuideDoc) {
    return
  }
  const docPath = path.join(REPO_ROOT, entry.userGuideDoc)
  expect(fs.existsSync(docPath), `${label}: missing ${entry.userGuideDoc}`).toBe(true)
  if (!entry.markerId) {
    return
  }
  const content = fs.readFileSync(docPath, 'utf8')
  expect(content, `${label}: marker ${entry.markerId}`).toContain(tabHelpMarker(entry.markerId))
}

describe('tabHelpContent', () => {
  it('covers every main tab id', () => {
    for (const tabId of MAIN_TAB_IDS) {
      expect(MAIN_TAB_HELP[tabId as MainTabId]).toBeDefined()
    }
  })

  it('main tab entries reference existing docs with markers when configured', () => {
    for (const [tabId, entry] of Object.entries(MAIN_TAB_HELP)) {
      assertGuideDoc(entry, `main:${tabId}`)
    }
  })

  it('settings sub tab entries reference existing docs with markers when configured', () => {
    for (const [subId, entry] of Object.entries(SETTINGS_SUB_TAB_HELP)) {
      assertGuideDoc(entry, `settings:${subId}`)
    }
  })

  it('resolveTabHelp prefers settings sub tab help on settings tab', () => {
    const entry = resolveTabHelp('settings', 'score_rules')
    expect(entry.userGuideDoc).toBe('docs/user-guides/score-rules.md')
    expect(entry.markerId).toBe('score_rules')
  })

  it('every settings sub tab id has help or falls back to settings main help', () => {
    for (const subId of SETTINGS_SUB_TAB_IDS) {
      const entry = resolveTabHelp('settings', subId)
      expect(entry.summary.length).toBeGreaterThan(0)
    }
  })
})
