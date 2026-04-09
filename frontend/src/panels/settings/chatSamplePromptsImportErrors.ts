import type { ZodIssue } from 'zod'
import { ZodError } from 'zod'

/**
 * プロンプトテンプレート JSON の読み取り・検証エラーを、画面向けの短文にまとめる。
 */
export function formatChatSamplePromptsFileParseError(err: unknown): string {
  if (err instanceof SyntaxError) {
    return 'JSON として解釈できません。UTF-8 のテキストか、本アプリの「ファイルにエクスポート」で保存したファイルか確認してください。'
  }
  if (err instanceof ZodError) {
    return describeChatSamplePromptsZodIssues(err.issues)
  }
  if (err instanceof Error) {
    const fromMessage = tryParseZodIssuesJson(err.message)
    if (fromMessage.length > 0) {
      return describeChatSamplePromptsZodIssues(fromMessage)
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

function describeChatSamplePromptsZodIssues(issues: readonly ZodIssue[]): string {
  if (issues.length === 0) {
    return 'ファイルの形式が正しくありません。'
  }

  const first = issues[0]
  const pathStr = pathKey(first)
  const issueCode = String(first.code)

  if (pathStr.includes('format') || issueCode === 'invalid_value' || issueCode === 'invalid_literal') {
    return '想定したプロンプトテンプレートファイルではありません。format が "vea-chat-sample-prompts" である必要があります。'
  }

  if (pathStr.includes('version')) {
    return 'version（バージョン番号）が不正です。1 以上の整数を指定してください。'
  }

  if (pathStr.includes('samples')) {
    return 'samples 配列の形式が正しくありません。各要素に id（非空文字列）・label・text があるか確認してください。'
  }

  return 'ファイルの形式が想定と異なります。本アプリの「ファイルにエクスポート」で保存した JSON か確認してください。'
}
