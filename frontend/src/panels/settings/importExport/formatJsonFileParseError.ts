import type { ZodIssue } from 'zod'
import { ZodError } from 'zod'

/**
 * Zod 4 では `ZodError` の `message` が JSON 配列（issues）になることがある。
 * `instanceof` が効かない境界でも拾う。
 */
export function tryParseZodIssuesJson(message: string): ZodIssue[] {
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

/** issues の path をドット区切り文字列にする。 */
export function zodIssuePathKey(issue: ZodIssue): string {
  return issue.path.map(String).join('.')
}

const JSON_SYNTAX_ERROR_MESSAGE =
  'JSON として解釈できません。UTF-8 のテキストか、本アプリの「ファイルにエクスポート」で保存したファイルか確認してください。'

/**
 * JSON ファイル読み込み・Zod 検証エラーを、ドメイン固有の describeZodIssues で日本語化する。
 */
export function formatJsonFileParseError(
  err: unknown,
  describeZodIssues: (issues: readonly ZodIssue[]) => string,
): string {
  if (err instanceof SyntaxError) {
    return JSON_SYNTAX_ERROR_MESSAGE
  }
  if (err instanceof ZodError) {
    return describeZodIssues(err.issues)
  }
  if (err instanceof Error) {
    const fromMessage = tryParseZodIssuesJson(err.message)
    if (fromMessage.length > 0) {
      return describeZodIssues(fromMessage)
    }
    return err.message
  }
  return String(err)
}
