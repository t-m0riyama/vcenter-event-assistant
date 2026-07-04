import type { ZodIssue } from 'zod'

import { formatImportApiError } from './importExport/fastApiImportError'
import { formatJsonFileParseError, zodIssuePathKey } from './importExport/formatJsonFileParseError'

/**
 * イベント種別ガイド JSON の読み取り・検証エラーを、画面向けの短文にまとめる。
 */
export function formatEventTypeGuidesFileParseError(err: unknown): string {
  return formatJsonFileParseError(err, describeEventTypeGuidesZodIssues)
}

/**
 * イベント種別ガイドファイル用 Zod issues を、技術的な JSON ではなく短文にまとめる。
 */
export function describeEventTypeGuidesZodIssues(issues: readonly ZodIssue[]): string {
  if (issues.length === 0) {
    return 'ファイルの形式が正しくありません。'
  }

  const first = issues[0]
  const pathStr = zodIssuePathKey(first)
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
  return formatImportApiError(err, {
    apiDetailJa: API_DETAIL_JA,
    format422Message: formatEventTypeGuidesImport422Message,
  })
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
