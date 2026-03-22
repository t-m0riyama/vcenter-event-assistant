import type { ZodIssue } from 'zod'
import { ZodError } from 'zod'

/**
 * イベント種別ガイド JSON の読み取り・検証エラーを、画面向けの短文にまとめる。
 */
export function formatEventTypeGuidesFileParseError(err: unknown): string {
  if (err instanceof SyntaxError) {
    return 'JSON として解釈できません。UTF-8 のテキストか、本アプリの「ファイルにエクスポート」で保存したファイルか確認してください。'
  }
  if (err instanceof ZodError) {
    return describeEventTypeGuidesZodIssues(err.issues)
  }
  if (err instanceof Error) {
    const fromMessage = tryParseZodIssuesJson(err.message)
    if (fromMessage.length > 0) {
      return describeEventTypeGuidesZodIssues(fromMessage)
    }
    return err.message
  }
  return String(err)
}

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
 * イベント種別ガイドファイル用 Zod issues を、技術的な JSON ではなく短文にまとめる。
 */
export function describeEventTypeGuidesZodIssues(issues: readonly ZodIssue[]): string {
  if (issues.length === 0) {
    return 'ファイルの形式が正しくありません。'
  }

  const first = issues[0]
  const pathStr = pathKey(first)
  const pathArr = first.path
  const issueCode = String(first.code)

  if (first.message.includes('重複')) {
    return 'ファイル内で同じイベント種別（event_type）が重複しています。種類ごとに 1 行だけにしてください。'
  }

  if (pathStr.includes('format') || issueCode === 'invalid_value' || issueCode === 'invalid_literal') {
    return '想定したイベント種別ガイドファイルではありません。format が "vea-event-type-guides" である必要があります。'
  }

  if (pathStr.includes('version')) {
    return 'version（バージョン番号）が不正です。1 以上の整数を指定してください。'
  }

  if (first.code === 'invalid_type' && pathArr.includes('event_type')) {
    return 'イベント種別（event_type）は文字列で指定してください。JSON では二重引用符（"…"）で囲み、数値や true/false にはできません。例: "vim.event.VmPoweredOn"'
  }

  if (first.code === 'invalid_type' && pathArr.includes('action_required')) {
    return '対処が必要（action_required）は true または false で指定してください。文字列で囲まないでください。'
  }

  if (pathStr.includes('event_type')) {
    return 'イベント種別（event_type）は 1〜512 文字の文字列として指定してください。'
  }

  if (pathStr.includes('general_meaning') || pathStr.includes('typical_causes') || pathStr.includes('remediation')) {
    return '意味・原因・対処の各フィールドは 8000 文字以内の文字列か null として指定してください。'
  }

  if (pathStr.includes('guides')) {
    return 'guides 配列の形式が正しくありません。各要素に event_type と action_required（真偽値）があるか確認してください。'
  }

  return 'ファイルの形式が想定と異なります。本アプリの「ファイルにエクスポート」で保存した JSON か確認してください。'
}

const API_DETAIL_JA: Record<string, string> = {
  'duplicate event_type in guides':
    'インポートするガイドの中に、同じイベント種別が重複しています。ファイルを修正するか、エクスポートし直してください。',
}

/**
 * `apiPost` が投げる `Error`（先頭に HTTP ステータスと JSON 本文）を画面向けに整形する。
 */
export function formatEventTypeGuidesImportApiError(err: unknown): string {
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
    return formatEventTypeGuidesImport422Message(detailText)
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

function formatEventTypeGuidesImport422Message(detailText: string | null): string {
  if (!detailText) {
    return 'サーバーが送信内容を検証できませんでした。guides の各行で event_type・各テキスト・action_required を確認してください。'
  }
  const lower = detailText.toLowerCase()
  if (
    lower.includes('event_type') ||
    lower.includes('guides') ||
    lower.includes('general_meaning') ||
    lower.includes('action_required')
  ) {
    return 'サーバーが送信内容を検証できませんでした。event_type は文字列、対処が必要は true/false、本文は文字数上限内か確認してください。'
  }
  return 'サーバーが送信内容を検証できませんでした。ガイドの値（文字数・形式）を確認してください。'
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
