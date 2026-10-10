import { describe, expect, it } from 'vitest'
import {
  applyAlertRuleEdit,
  discardAlertRuleDraft,
  draftKey,
  draftValues,
  reconcileAlertRuleDrafts,
  type AlertRuleDraftSource,
  type AlertRuleDrafts,
} from './alertRuleDrafts'

const rule = (patch: Partial<AlertRuleDraftSource> = {}): AlertRuleDraftSource => ({
  id: 7,
  created_at: '2026-10-01T00:00:00Z',
  name: 'High score',
  alert_level: 'critical',
  is_enabled: true,
  config: { threshold: 80, cooldown_minutes: 30 },
  ...patch,
})

const key = draftKey(rule())

describe('alertRuleDrafts', () => {
  it('変えた項目だけを持ち、元の値に戻したら外し、何も残らなければ下書きごと捨てる', () => {
    let drafts: AlertRuleDrafts = {}
    drafts = applyAlertRuleEdit(drafts, rule(), { alert_level: 'warning' })
    expect(drafts[key].edits).toEqual({ alert_level: 'warning' })
    drafts = applyAlertRuleEdit(drafts, rule(), { name: 'Renamed' })
    expect(drafts[key].edits).toEqual({ alert_level: 'warning', name: 'Renamed' })
    drafts = applyAlertRuleEdit(drafts, rule(), { alert_level: 'critical' })
    expect(drafts[key].edits).toEqual({ name: 'Renamed' })
    drafts = applyAlertRuleEdit(drafts, rule(), { name: 'High score' })
    expect(drafts).toEqual({})
  })

  it('編集欄にはサーバの値に変えた項目だけを重ねて出す', () => {
    const drafts = applyAlertRuleEdit({}, rule(), { name: 'Renamed' })
    const reloaded = rule({ alert_level: 'error' })
    expect(draftValues(reloaded, drafts[key])).toMatchObject({ name: 'Renamed', alert_level: 'error' })
  })

  it('読み直しで変化が無ければ同じオブジェクトを返す', () => {
    const drafts = applyAlertRuleEdit({}, rule(), { name: 'Renamed' })
    expect(reconcileAlertRuleDrafts(drafts, [rule()])).toBe(drafts)
  })

  it('触っていない項目がサーバで変わっても競合にせず、base を読み直した値にする', () => {
    const drafts = applyAlertRuleEdit({}, rule(), { name: 'Renamed' })
    const next = reconcileAlertRuleDrafts(drafts, [rule({ alert_level: 'error', is_enabled: false })])
    expect(next[key]).toMatchObject({ edits: { name: 'Renamed' }, conflict: false })
    expect(next[key].base).toMatchObject({ alert_level: 'error', is_enabled: false })
  })

  it('変えた項目がサーバで別の値に変わったら競合にし、捨てるまで印を残す', () => {
    let drafts = applyAlertRuleEdit({}, rule(), { alert_level: 'warning' })
    drafts = reconcileAlertRuleDrafts(drafts, [rule({ alert_level: 'error' })])
    expect(drafts[key]).toMatchObject({ edits: { alert_level: 'warning' }, conflict: true })
    // 次の読み直しで変化が無くても印は消えない
    drafts = reconcileAlertRuleDrafts(drafts, [rule({ alert_level: 'error' })])
    expect(drafts[key].conflict).toBe(true)
    expect(discardAlertRuleDraft(drafts, rule())).toEqual({})
  })

  it('利用者の値とサーバの値が同じになった項目は外し、その後サーバが変わっても重ねない', () => {
    // A（critical）→ B（warning）に編集し、サーバも B になる
    let drafts = applyAlertRuleEdit({}, rule(), { alert_level: 'warning', name: 'Renamed' })
    drafts = reconcileAlertRuleDrafts(drafts, [rule({ alert_level: 'warning' })])
    expect(drafts[key]).toMatchObject({ edits: { name: 'Renamed' }, conflict: false })
    // その後サーバが C（error）になっても、古い B は重ならず、競合にもならない
    drafts = reconcileAlertRuleDrafts(drafts, [rule({ alert_level: 'error' })])
    expect(drafts[key]).toMatchObject({ edits: { name: 'Renamed' }, conflict: false })
    expect(draftValues(rule({ alert_level: 'error' }), drafts[key]).alert_level).toBe('error')
  })

  it('変えた項目がすべてサーバと同じになったら下書きごと捨てる', () => {
    let drafts = applyAlertRuleEdit({}, rule(), { alert_level: 'warning' })
    drafts = reconcileAlertRuleDrafts(drafts, [rule({ alert_level: 'warning' })])
    expect(drafts).toEqual({})
  })

  it('元の値に戻した項目は残らないので、後でサーバが変わっても上書きしない', () => {
    let drafts = applyAlertRuleEdit({}, rule(), { alert_level: 'warning', name: 'Renamed' })
    drafts = applyAlertRuleEdit(drafts, rule(), { alert_level: 'critical' })
    drafts = reconcileAlertRuleDrafts(drafts, [rule({ alert_level: 'error' })])
    expect(drafts[key]).toMatchObject({ edits: { name: 'Renamed' }, conflict: false })
  })

  it('一覧から消えたルールと、id が使い回されたルールの下書きは捨てる', () => {
    const drafts = applyAlertRuleEdit({}, rule(), { name: 'Renamed' })
    expect(reconcileAlertRuleDrafts(drafts, [])).toEqual({})
    const reused = rule({ name: 'New rule', created_at: '2026-10-10T00:00:00Z' })
    const next = reconcileAlertRuleDrafts(drafts, [reused])
    expect(next).toEqual({})
    expect(draftValues(reused, next[draftKey(reused)]).name).toBe('New rule')
  })

  it('競合の後に変えた項目を元に戻したら、下書きごと捨てる', () => {
    let drafts = applyAlertRuleEdit({}, rule(), { alert_level: 'warning' })
    drafts = reconcileAlertRuleDrafts(drafts, [rule({ alert_level: 'error' })])
    // base は読み直した error になっている
    drafts = applyAlertRuleEdit(drafts, rule({ alert_level: 'error' }), { alert_level: 'error' })
    expect(drafts).toEqual({})
  })
})
