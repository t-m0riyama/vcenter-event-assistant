import type { EventTypeGuideSnippet } from '../api/schemas'

/**
 * イベント種別ガイドの本文（意味・原因・対処）。一覧の details とホバー用ポップアップで共通利用する。
 */
export function EventTypeGuideBody({ guide }: { guide: EventTypeGuideSnippet }) {
  return (
    <dl className="event-type-guide-dl">
      <dt>一般的な意味</dt>
      <dd>{guide.general_meaning?.trim() ? guide.general_meaning : '—'}</dd>
      <dt>想定される原因</dt>
      <dd>{guide.typical_causes?.trim() ? guide.typical_causes : '—'}</dd>
      <dt>対処方法</dt>
      <dd>{guide.remediation?.trim() ? guide.remediation : '—'}</dd>
    </dl>
  )
}
