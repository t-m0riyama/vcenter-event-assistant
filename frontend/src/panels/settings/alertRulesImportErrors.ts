import type { ZodIssue } from 'zod'

import { formatImportApiError } from './importExport/fastApiImportError'
import { formatJsonFileParseError, zodIssuePathKey } from './importExport/formatJsonFileParseError'

export function formatAlertRulesFileParseError(err: unknown): string {
  return formatJsonFileParseError(err, describeAlertRulesZodIssues)
}

export function describeAlertRulesZodIssues(issues: readonly ZodIssue[]): string {
  if (issues.length === 0) return 'ファイルの形式が正しくありません。'

  const first = issues[0]
  const pathStr = zodIssuePathKey(first)
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
  return formatImportApiError(err, {
    apiDetailJa: API_DETAIL_JA,
    format422Message: (detailText) =>
      detailText
        ? 'サーバーが送信内容を検証できませんでした。ルールの値（name、rule_type、alert_level、config）を確認してください。'
        : 'サーバーが送信内容を検証できませんでした。ルールの値（name、rule_type、alert_level、config）を確認してください。',
  })
}
