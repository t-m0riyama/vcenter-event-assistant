import type { DigestRead } from '../../api/schemas'

/**
 * `kind` をファイル名の 1 セグメントとして使えるよう ASCII 安全な文字列に正規化する。
 */
function sanitizeKindSegment(kind: string): string {
  const s = kind
    .replace(/[^a-zA-Z0-9._-]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_|_$/g, '')
  return s.length > 0 ? s : 'kind'
}

/**
 * ダイジェストを Markdown ファイルとして保存するときのファイル名を返す。
 * `period_start` の UTC 日付（`YYYY-MM-DD`）を含める。
 */
export function buildDigestDownloadFilename(d: DigestRead): string {
  const dateUtc = d.period_start.slice(0, 10)
  const kindSeg = sanitizeKindSegment(d.kind)
  return `digest-${d.id}-${kindSeg}-${dateUtc}.md`
}
