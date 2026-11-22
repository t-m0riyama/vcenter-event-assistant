/**
 * 設定 → アラートの行の中で編集している値（下書き）の扱い。
 *
 * 下書きは比較の基準になるサーバの値・版・ルール種別と、利用者の変更を持つ。
 * - `base`: 編集開始時または再照合時に読んだ値
 * - `baseRevision` / `baseRuleType`: 基準の版とルール種別
 * - `edits`: 利用者が `base` から変えた項目だけ
 * - `conflict`: 再照合や保存で、この下書きを適用できない変更が見つかった
 *
 * 一覧を読み直すたびに `reconcileAlertRuleDrafts` で 3 つを比べ直す。
 * - 利用者が触っていない項目は、読み直した値をそのまま出す（`edits` に無いので重ならない）
 * - 利用者の値とサーバの値が同じになった項目は `edits` から外す
 * - 利用者が変えた項目がサーバで別の値に変わっていたら `conflict` にし、利用者が
 *   「編集を破棄して読み直す」を選ぶまで保存させない（黙ってどちらかで上書きしない）
 */

export type AlertLevel = 'critical' | 'error' | 'warning'

export interface EditDraft {
  name: string
  alert_level: AlertLevel
  is_enabled: boolean
  threshold: number
  metric_key: string
  cooldown_minutes: number
}

export interface AlertRuleDraftSource {
  id: number
  created_at: string
  revision: string
  name: string
  rule_type: 'event_score' | 'metric_threshold'
  alert_level: string
  is_enabled: boolean
  config: { threshold?: number; metric_key?: string; cooldown_minutes?: number }
}

export interface AlertRuleDraft {
  base: EditDraft
  baseRevision: string
  baseRuleType: AlertRuleDraftSource['rule_type']
  edits: Partial<EditDraft>
  conflict: boolean
}

export type AlertRuleDrafts = Record<string, AlertRuleDraft>

/**
 * 下書きのキー。削除した後に同じ id が使い回されても（SQLite など）、別のルールの下書きを
 * 重ねないよう作成日時も含める。
 */
export function draftKey(rule: Pick<AlertRuleDraftSource, 'id' | 'created_at'>): string {
  return `${rule.id}:${rule.created_at}`
}

/** サーバのルールを、編集欄に出す値の形にする。 */
export function editValuesFromRule(rule: AlertRuleDraftSource): EditDraft {
  return {
    name: rule.name,
    alert_level: rule.alert_level as AlertLevel,
    is_enabled: rule.is_enabled,
    threshold: Number(rule.config.threshold ?? 0),
    metric_key: rule.config.metric_key ?? '',
    cooldown_minutes: Number(rule.config.cooldown_minutes ?? 10),
  }
}

function fieldsOf(values: Partial<EditDraft>): (keyof EditDraft)[] {
  return Object.keys(values) as (keyof EditDraft)[]
}

/** 編集欄に出す値（サーバの値に、利用者が変えた項目だけを重ねる）。 */
export function draftValues(rule: AlertRuleDraftSource, draft: AlertRuleDraft | undefined): EditDraft {
  return { ...editValuesFromRule(rule), ...draft?.edits }
}

/**
 * 利用者の入力を下書きに入れる。`base` と同じ値に戻した項目は外し、何も残らなければ
 * 下書きごと捨てる（変えた項目が無ければ、競合の印も意味を持たない）。
 */
export function applyAlertRuleEdit(
  drafts: AlertRuleDrafts,
  rule: AlertRuleDraftSource,
  patch: Partial<EditDraft>,
): AlertRuleDrafts {
  const key = draftKey(rule)
  const prev = drafts[key] ?? {
    base: editValuesFromRule(rule),
    baseRevision: rule.revision,
    baseRuleType: rule.rule_type,
    edits: {},
    conflict: false,
  }
  const edits: Partial<EditDraft> = { ...prev.edits, ...patch }
  for (const field of fieldsOf(edits)) {
    if (edits[field] === prev.base[field]) delete edits[field]
  }
  const next = { ...drafts }
  if (fieldsOf(edits).length === 0) delete next[key]
  else next[key] = { ...prev, edits }
  return next
}

/** 下書きを捨てる（保存・削除・「編集を破棄して読み直す」の後）。 */
export function discardAlertRuleDraft(drafts: AlertRuleDrafts, rule: AlertRuleDraftSource): AlertRuleDrafts {
  const key = draftKey(rule)
  if (!(key in drafts)) return drafts
  const next = { ...drafts }
  delete next[key]
  return next
}

/** 保存時にサーバーが変更または削除を検出した行を競合にする。 */
export function markAlertRuleDraftConflict(drafts: AlertRuleDrafts, rule: AlertRuleDraftSource): AlertRuleDrafts {
  const key = draftKey(rule)
  const draft = drafts[key]
  if (!draft || draft.conflict) return drafts
  return { ...drafts, [key]: { ...draft, conflict: true } }
}

/**
 * 読み直した一覧と下書きを比べ直す。変化が無ければ同じオブジェクトを返す（再描画を増やさない）。
 * - 一覧に無いルール（削除されたもの、id が使い回されたもの）の下書きは捨てる
 * - `base` と版を読み直した値にする
 * - 利用者の値とサーバの値が同じになった項目は外す
 * - ルール種別や編集中の項目もサーバで変わっていたら競合にする
 */
export function reconcileAlertRuleDrafts(
  drafts: AlertRuleDrafts,
  rules: readonly AlertRuleDraftSource[],
): AlertRuleDrafts {
  const byKey = new Map(rules.map((rule) => [draftKey(rule), rule]))
  let changed = false
  const next: AlertRuleDrafts = {}
  for (const [key, draft] of Object.entries(drafts)) {
    const rule = byKey.get(key)
    if (!rule) {
      changed = true
      continue
    }
    if (draft.conflict) {
      next[key] = draft
      continue
    }
    if (rule.rule_type !== draft.baseRuleType) {
      changed = true
      next[key] = { ...draft, conflict: true }
      continue
    }
    const current = editValuesFromRule(rule)
    const edits: Partial<EditDraft> = {}
    let conflict = false
    for (const field of fieldsOf(draft.edits)) {
      const mine = draft.edits[field]
      if (mine === current[field]) continue
      if (current[field] !== draft.base[field]) conflict = true
      ;(edits as Record<string, unknown>)[field] = mine
    }
    const baseChanged = fieldsOf(current).some((field) => current[field] !== draft.base[field])
    const editsChanged = fieldsOf(edits).length !== fieldsOf(draft.edits).length
    if (fieldsOf(edits).length === 0) {
      changed = true
      continue
    }
    if (!baseChanged && !editsChanged && !conflict && rule.revision === draft.baseRevision) {
      next[key] = draft
      continue
    }
    changed = true
    next[key] = { ...draft, base: current, baseRevision: rule.revision, edits, conflict }
  }
  return changed ? next : drafts
}
