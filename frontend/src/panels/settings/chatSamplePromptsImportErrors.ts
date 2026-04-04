import type { ZodIssue } from 'zod'
import { ZodError } from 'zod'

/**
 * チャットサンプル JSON の読み取り・検証エラーを、画面向けの短文にまとめる。
 */
export function formatChatSamplePromptsFileParseError(err: unknown): string {
  if (err instanceof SyntaxError) {
    return 'JSON として解釈できません。UTF-8 のテキストか、本アプリの「ファイルにエクスポート」で保存したファイルか確認してください。'
  }
  if (err instanceof ZodError) {
    return describeChatSamplePromptsZodIssues(err.issues)
  }
  if (err instanceof Error) {
    return err.message
  }
  return String(err)
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
    return '想定したチャットサンプルファイルではありません。format が "vea-chat-sample-prompts" である必要があります。'
  }

  if (pathStr.includes('version')) {
    return 'version（バージョン番号）が不正です。1 以上の整数を指定してください。'
  }

  if (pathStr.includes('samples')) {
    return 'samples 配列の形式が正しくありません。各要素に id（非空文字列）・label・text があるか確認してください。'
  }

  return 'ファイルの形式が想定と異なります。本アプリの「ファイルにエクスポート」で保存した JSON か確認してください。'
}
