import type { ZodIssue } from 'zod'
import { ZodError } from 'zod'

/**
 * スコアルール JSON の読み取り・検証エラーを、画面向けの短文にまとめる。
 */
export function formatScoreRulesFileParseError(err: unknown): string {
  if (err instanceof SyntaxError) {
    return 'JSON として解釈できません。UTF-8 のテキストか、本アプリの「ファイルにエクスポート」で保存したファイルか確認してください。'
  }
  if (err instanceof ZodError) {
    return describeScoreRulesZodIssues(err.issues)
  }
  if (err instanceof Error) {
    const fromMessage = tryParseZodIssuesJson(err.message)
    if (fromMessage.length > 0) {
      return describeScoreRulesZodIssues(fromMessage)
    }
    return err.message
  }
  return String(err)
}

/**
 * Zod 4 では `ZodError` の `message` が JSON 配列（issues）になることがある。`instanceof` が効かない境界でも拾う。
 */
function tryParseZodIssuesJson(message: string): ZodIssue[] {
  const t = message.trim()
  if (!t.startsWith('[')) return []
  try {
    const parsed = JSON.parse(t) as unknown
    if (!Array.isArray(parsed) || parsed.length === 0) return []
    return parsed as ZodIssue[]
  } catch {
    return []
  }
}

function pathKey(issue: ZodIssue): string {
  return issue.path.map(String).join('.')
}

/**
 * スコアルールファイル用 Zod issues を、技術的な JSON ではなく短文にまとめる。
 */
export function describeScoreRulesZodIssues(issues: readonly ZodIssue[]): string {
  if (issues.length === 0) {
    return 'ファイルの形式が正しくありません。'
  }

  const first = issues[0]
  const pathStr = pathKey(first)
  const pathArr = first.path
  /** Zod 4 は `z.literal` 不一致を `invalid_value`。旧 Zod / シリアライズ済み JSON では `invalid_literal` のことがある。 */
  const issueCode = String(first.code)

  if (first.message.includes('重複')) {
    return 'ファイル内で同じイベント種別（event_type）が重複しています。種類ごとに 1 行だけにしてください。'
  }

  if (pathStr.includes('format') || issueCode === 'invalid_value' || issueCode === 'invalid_literal') {
    return '想定したスコアルールファイルではありません。format が "vea-event-score-rules" である必要があります。'
  }

  if (pathStr.includes('version')) {
    return 'version（バージョン番号）が不正です。1 以上の整数を指定してください。'
  }

  if (first.code === 'invalid_type' && pathArr.includes('event_type')) {
    return 'イベント種別（event_type）は文字列で指定してください。JSON では二重引用符（"…"）で囲み、数値や true/false にはできません。例: "vim.event.VmPoweredOn"'
  }

  if (first.code === 'invalid_type' && pathArr.includes('score_delta')) {
    return '加算（score_delta）は整数（例: 5 や -10）で指定してください。文字列で囲まないでください。'
  }

  if (pathStr.includes('event_type')) {
    return 'イベント種別（event_type）は 1〜512 文字の文字列として指定してください。'
  }

  if (pathStr.includes('score_delta')) {
    return '加算（score_delta）は -10000〜10000 の整数として指定してください。'
  }

  if (pathStr.includes('rules')) {
    return 'rules 配列の形式が正しくありません。各要素に event_type（文字列）と score_delta（整数）があるか確認してください。'
  }

  return 'ファイルの形式が想定と異なります。本アプリの「ファイルにエクスポート」で保存した JSON か確認してください。'
}

/** FastAPI の `detail` 文字列を日本語に寄せる（既知のキーのみ）。 */
const API_DETAIL_JA: Record<string, string> = {
  'duplicate event_type in rules':
    'インポートするルールの中に、同じイベント種別が重複しています。ファイルを修正するか、エクスポートし直してください。',
}

/**
 * `apiPost` が投げる `Error`（先頭に HTTP ステータスと JSON 本文）を画面向けに整形する。
 */
export function formatScoreRulesImportApiError(err: unknown): string {
  if (!(err instanceof Error)) {
    return String(err)
  }
  const raw = err.message
  if (/failed to fetch/i.test(raw) || raw.includes('NetworkError')) {
    return 'ネットワークに接続できませんでした。接続を確認してから再度お試しください。'
  }
  const parsed = tryParseFastApiErrorBody(raw)
  if (!parsed) {
    return `インポートに失敗しました。${raw.length > 200 ? `${raw.slice(0, 200)}…` : raw}`
  }

  const { status, detailText } = parsed

  if (detailText && API_DETAIL_JA[detailText]) {
    return API_DETAIL_JA[detailText]
  }

  if (status === 422) {
    return formatScoreRulesImport422Message(detailText)
  }

  if (status === 400 && detailText) {
    return `リクエストを受け付けられませんでした。${detailText}`
  }

  if (status >= 500) {
    return 'サーバー側でエラーが発生しました。しばらくしてから再度お試しください。'
  }

  return `インポートに失敗しました（${status}）。${detailText ?? ''}`.trim()
}

function tryParseFastApiErrorBody(message: string): {
  status: number
  detailText: string | null
} | null {
  const head = message.match(/^(\d{3})\s+/)
  if (!head) return null
  const status = Number(head[1])
  const jsonStart = message.indexOf('{')
  if (jsonStart === -1) return { status, detailText: message.slice(head[0].length).trim() || null }

  try {
    const body = JSON.parse(message.slice(jsonStart)) as { detail?: unknown }
    const detailText = flattenFastApiDetail(body.detail)
    return { status, detailText }
  } catch {
    return { status, detailText: message.slice(head[0].length).trim() || null }
  }
}

/**
 * インポート POST の 422（Pydantic）を、ユーザー向けにまとめる。
 */
function formatScoreRulesImport422Message(detailText: string | null): string {
  if (!detailText) {
    return 'サーバーが送信内容を検証できませんでした。ルールの各行で、event_type は文字列、score_delta は整数（-10000〜10000）か確認してください。'
  }
  const lower = detailText.toLowerCase()
  if (
    lower.includes('event_type') ||
    lower.includes('rules') ||
    lower.includes('score_delta')
  ) {
    return 'サーバーが送信内容を検証できませんでした。ルールの各行で、event_type は文字列（JSON では "…" で囲む）、score_delta は整数（-10000〜10000）か確認してください。'
  }
  return 'サーバーが送信内容を検証できませんでした。ルールの値（文字数・加算の範囲）を確認してください。'
}

function flattenFastApiDetail(detail: unknown): string | null {
  if (detail == null) return null
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (item && typeof item === 'object' && 'msg' in item) {
        const loc = 'loc' in item && Array.isArray((item as { loc?: unknown }).loc)
          ? String((item as { loc: unknown[] }).loc.join('.'))
          : ''
        const msg = String((item as { msg: unknown }).msg)
        return loc ? `${loc}: ${msg}` : msg
      }
      return JSON.stringify(item)
    })
    return parts.join(' / ')
  }
  return JSON.stringify(detail)
}
