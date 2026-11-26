import type { ReactNode } from 'react'

import type { TimelineConfigDiff } from '../../api/schemas'
import { formatIsoInTimeZone, parseApiUtcInstantMs } from '../../datetime/formatIsoInTimeZone'

type DiffValue = TimelineConfigDiff['old_value']

function elementAction(diff: TimelineConfigDiff) {
  if (diff.element === null || diff.attribute !== null) return null
  if (diff.old_value === null && diff.new_value !== null) return '追加'
  if (diff.new_value === null && diff.old_value !== null) return '削除'
  return null
}

function replacementKey(diff: TimelineConfigDiff) {
  // 対象が記録されていない保存済みの差分は、別の対象と組になるおそれがある。
  if (!diff.vcenter_id || !diff.entity_moid) return null
  return JSON.stringify([diff.vcenter_id, diff.entity_moid, diff.observed_at, diff.category, diff.element])
}

function combineReplacements(items: readonly TimelineConfigDiff[]) {
  const removals = new Map<string, number[]>()
  for (const [index, item] of items.entries()) {
    const key = replacementKey(item)
    if (!key || elementAction(item) !== '削除') continue
    const matching = removals.get(key) ?? []
    matching.push(index)
    removals.set(key, matching)
  }

  const pairs = new Map<number, { removed: TimelineConfigDiff; added: TimelineConfigDiff }>()
  const hidden = new Set<number>()
  for (const [addedIndex, added] of items.entries()) {
    const key = replacementKey(added)
    if (!key || elementAction(added) !== '追加') continue
    const removedIndex = removals.get(key)?.shift()
    if (removedIndex === undefined) continue
    pairs.set(Math.min(removedIndex, addedIndex), { removed: items[removedIndex], added })
    hidden.add(Math.max(removedIndex, addedIndex))
  }
  return items.flatMap((item, index) => hidden.has(index) ? [] : [{ item, pair: pairs.get(index) }])
}

function displayValue(value: DiffValue, truncated: boolean): { text: string; cut: boolean } {
  // 切り詰めのある行は、両側の値が JSON の文字列として返る。
  if (truncated && typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      // 数値が途中まででも JSON として読める場合がある。値の文字列はそのまま保つ。
      return { text: typeof parsed === 'number' ? value : valueText(parsed), cut: false }
    } catch {
      // 文字列の先頭の引用符と途中で切れたエスケープを取り除き、完全なエスケープをデコードする。
      const text = value.startsWith('"') ? value.slice(1).replace(
        /\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4})|\\(?:u[0-9a-fA-F]{0,3})?$/g,
        (escape) => escape.length === 1 || (escape[1] === 'u' && escape.length < 6)
          ? ''
          : JSON.parse('"' + escape + '"'),
      ) : value
      return { text, cut: true }
    }
  }
  return { text: valueText(value), cut: false }
}

function valueText(value: DiffValue): string {
  if (value === null) return '未設定'
  if (value === '') return '（空）'
  if (typeof value === 'boolean') return value ? 'はい' : 'いいえ'
  return typeof value === 'string' ? value : JSON.stringify(value)
}

function ElementValues({ value, label, truncated }: { value: DiffValue; label: string; truncated: boolean }) {
  return (
    <div className="timeline-config-diff-list__values">
      <strong>{label}</strong>
      {value !== null && typeof value === 'object' && !Array.isArray(value) ? (
        <ul>
          {Object.entries(value).map(([key, field]) => <li key={key}>{key}: {valueText(field)}</li>)}
        </ul>
      ) : <div>{displayValue(value, truncated).text}{truncated && '（一部を省略）'}</div>}
    </div>
  )
}

function AttributeValues({ item, description, width }: {
  item: TimelineConfigDiff
  description: string
  width: ReactNode
}) {
  const oldValue = displayValue(item.old_value, item.truncated)
  const newValue = displayValue(item.new_value, item.truncated)
  return (
    <>
      <span>
        {description}: {oldValue.text}{oldValue.cut && '（一部を省略）'} → {newValue.text}{newValue.cut && '（一部を省略）'}
      </span>
      {' '}{width}
      {item.truncated && !oldValue.cut && !newValue.cut && <span>（値の一部を省略）</span>}
    </>
  )
}

export function TimelineConfigDiffList({ items, timeZone, firstSuccessAt, showTargets = false }: {
  items: readonly TimelineConfigDiff[]
  timeZone: string
  firstSuccessAt?: string | null
  showTargets?: boolean
}) {
  if (!items.length) return null
  const showTime = (at: string) => <time dateTime={at}>{formatIsoInTimeZone(at, timeZone)}</time>

  return (
    <ul className="timeline-config-diff-list" aria-label="観測した構成の差分">
      {combineReplacements(items).map(({ item, pair }) => {
        const action = elementAction(item)
        const description = [
          showTargets ? (item.entity_name || item.entity_moid) : null,
          item.category_label,
          pair?.added.element_label ?? item.element_label ?? item.element,
          item.attribute_label ?? item.attribute,
        ].filter(Boolean).join('・')
        const width = (
          <span className="timeline-config-diff-list__time">
            （{showTime(item.changed_after)} から {showTime(item.observed_at)} の間）
            {firstSuccessAt && parseApiUtcInstantMs(item.observed_at) < parseApiUtcInstantMs(firstSuccessAt) && ' 記録をやり直す前の値'}
          </span>
        )
        return (
          <li key={item.id}>
            {pair ? (
              <details>
                <summary><span>{description}・入れ替わり</span> {width}</summary>
                <ElementValues value={pair.removed.old_value} label="削除した要素" truncated={pair.removed.truncated} />
                <ElementValues value={pair.added.new_value} label="追加した要素" truncated={pair.added.truncated} />
              </details>
            ) : action ? (
              <details>
                <summary><span>{description}・{action}</span> {width}</summary>
                <ElementValues
                  value={action === '追加' ? item.new_value : item.old_value}
                  label={action === '追加' ? '追加した要素' : '削除した要素'}
                  truncated={item.truncated}
                />
              </details>
            ) : (
              <AttributeValues item={item} description={description} width={width} />
            )}
          </li>
        )
      })}
    </ul>
  )
}
