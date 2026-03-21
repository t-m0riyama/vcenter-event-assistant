import {
  EVENT_TEXT_FILTER_SUMMARY_CLIP,
  EVENT_TEXT_FILTER_SUMMARY_MAX,
} from './constants'

function clipForFilterSummary(s: string, max: number): string {
  const t = s.trim()
  if (!t) return ''
  return t.length <= max ? t : `${t.slice(0, max - 1)}…`
}

/** One-line preview for collapsed 種別/重大度/メッセージ/コメント filters. */
export function summarizeEventTextFilters(
  filterEventType: string,
  filterSeverity: string,
  filterMessage: string,
  filterComment: string,
): string {
  const pairs: Array<{ label: string; value: string }> = [
    { label: '種別', value: filterEventType },
    { label: '重大度', value: filterSeverity },
    { label: 'メッセージ', value: filterMessage },
    { label: 'コメント', value: filterComment },
  ]
  const active = pairs.filter((p) => p.value.trim())
  if (active.length === 0) return '条件なし'
  let out = active
    .map((p) => `${p.label}「${clipForFilterSummary(p.value, EVENT_TEXT_FILTER_SUMMARY_CLIP)}」`)
    .join(' · ')
  if (out.length > EVENT_TEXT_FILTER_SUMMARY_MAX) {
    out = `${out.slice(0, EVENT_TEXT_FILTER_SUMMARY_MAX - 1)}…`
  }
  return out
}
