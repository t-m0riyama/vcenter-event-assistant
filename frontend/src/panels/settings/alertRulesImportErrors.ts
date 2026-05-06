import type { ZodIssue } from 'zod'
import { ZodError } from 'zod'

export function formatAlertRulesFileParseError(err: unknown): string {
  if (err instanceof SyntaxError) {
    return 'JSON として解釈できません。UTF-8 のテキストか、本アプリの「ファイルにエクスポート」で保存したファイルか確認してください。'
  }
  if (err instanceof ZodError) {
    return describeAlertRulesZodIssues(err.issues)
  }
  if (err instanceof Error) {
    const fromMessage = tryParseZodIssuesJson(err.message)
    if (fromMessage.length > 0) return describeAlertRulesZodIssues(fromMessage)
    return err.message
  }
  return String(err)
}

function tryParseZodIssuesJson(message: string): ZodIssue[] {
  const text = message.trim()
  if (!text.startsWith('[')) return []
  try {
    const parsed = JSON.parse(text) as unknown
    if (!Array.isArray(parsed) || parsed.length === 0) return []
    return parsed as ZodIssue[]
  } catch {
    return []
  }
}

function pathKey(issue: ZodIssue): string {
  return issue.path.map(String).join('.')
}

export function describeAlertRulesZodIssues(issues: readonly ZodIssue[]): string {
  if (issues.length === 0) return 'ファイルの形式が正しくありません。'

  const first = issues[0]
  const pathStr = pathKey(first)
  const pathArr = first.path
  const issueCode = String(first.code)

  if (first.message.includes('重複')) {
    return 'ファイル内で同じルール名（name）が重複しています。ルール名ごとに 1 行だけにしてください。'
  }
  if (pathStr.includes('format') || issueCode === 'invalid_value' || issueCode === 'invalid_literal') {
    return '想定したアラートルールファイルではありません。format が "vea-alert-rules" である必要があります。'
  }
  if (pathStr.includes('version')) {
    return 'version（バージョン番号）が不正です。1 以上の整数を指定してください。'
  }
  if (first.code === 'invalid_type' && pathArr.includes('name')) {
    return 'ルール名（name）は文字列で指定してください。'
  }
  if (pathStr.includes('name')) {
    return 'ルール名（name）は 1〜255 文字の文字列として指定してください。'
  }
  if (pathStr.includes('rule_type')) {
    return 'rule_type は "event_score" または "metric_threshold" を指定してください。'
  }
  if (pathStr.includes('alert_level')) {
    return 'alert_level は "critical" / "error" / "warning" のいずれかを指定してください。'
  }
  if (pathStr.includes('is_enabled')) {
    return 'is_enabled は true または false で指定してください。'
  }
  if (pathStr.includes('rules')) {
    return 'rules 配列の形式が正しくありません。各要素に name、rule_type、is_enabled、alert_level、config があるか確認してください。'
  }

  return 'ファイルの形式が想定と異なります。本アプリの「ファイルにエクスポート」で保存した JSON か確認してください。'
}

const API_DETAIL_JA: Record<string, string> = {
  'duplicate name in rules':
    'インポートするルールの中に、同じルール名が重複しています。ファイルを修正するか、エクスポートし直してください。',
}

export function formatAlertRulesImportApiError(err: unknown): string {
  if (!(err instanceof Error)) return String(err)

  const raw = err.message
  if (/failed to fetch/i.test(raw) || raw.includes('NetworkError')) {
    return 'ネットワークに接続できませんでした。接続を確認してから再度お試しください。'
  }
  const parsed = tryParseFastApiErrorBody(raw)
  if (!parsed) {
    return `インポートに失敗しました。${raw.length > 200 ? `${raw.slice(0, 200)}…` : raw}`
  }

  const { status, detailText } = parsed
  if (detailText && API_DETAIL_JA[detailText]) return API_DETAIL_JA[detailText]
  if (status === 422) return 'サーバーが送信内容を検証できませんでした。ルールの値（name、rule_type、alert_level、config）を確認してください。'
  if (status === 400 && detailText) return `リクエストを受け付けられませんでした。${detailText}`
  if (status >= 500) return 'サーバー側でエラーが発生しました。しばらくしてから再度お試しください。'
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
    return { status, detailText: flattenFastApiDetail(body.detail) }
  } catch {
    return { status, detailText: message.slice(head[0].length).trim() || null }
  }
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
