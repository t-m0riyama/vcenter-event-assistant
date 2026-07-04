import type { ChatSamplePromptRow } from './chatSamplePromptTypes'

/** 構造化 Markdown 出力を促すスニペット末尾の共通指示。 */
const STRUCTURED_OUTPUT_FOOTER =
  '上記の見出し（##）は必ずすべて出力してください。該当データが無いセクションは「該当なし（入力 JSON に含まれていません）」と記載してください。事実・数値は JSON の値のみに基づき、因果は断定しないでください。'

/**
 * 初回・移行時に localStorage へシードする既定サンプル（コード同梱）。
 * 保存後はユーザーが編集・削除可能。
 */
export const INITIAL_CHAT_SAMPLE_PROMPTS: readonly ChatSamplePromptRow[] = [
  {
    id: 'default-sample-period-summary',
    label: '期間の要約',
    text: [
      '以下の Markdown 形式で、この期間のイベントと傾向を回答してください。',
      '',
      '## 概要',
      '（期間全体の要約。total_events と要注意件数）',
      '',
      '## 上位イベント（重要度順）',
      '（top_notable_event_groups を重要度順に箇条書き。種別・件数・occurred_at_first / occurred_at_last）',
      '',
      '## イベント種別の内訳',
      '（top_event_types の上位）',
      '',
      '## 時系列上の変化',
      '（event_time_buckets がある場合の傾向）',
      '',
      STRUCTURED_OUTPUT_FOOTER,
    ].join('\n'),
  },
  {
    id: 'default-sample-power-events',
    label: '電源・可用性',
    text: [
      '以下の Markdown 形式で、この期間の電源操作・可用性に関連するイベントの傾向を回答してください。',
      '',
      '## 概要',
      '（電源操作・可用性に関連するイベントの有無と全体傾向）',
      '',
      '## 該当イベント',
      '（関連しそうな event_type を列挙。種別・件数・時刻）',
      '',
      '## 時系列',
      '（集中時刻・増減の傾向）',
      '',
      '## 所見',
      '（傾向のみ。因果断定はしない）',
      '',
      STRUCTURED_OUTPUT_FOOTER,
    ].join('\n'),
  },
  {
    id: 'default-sample-alerts',
    label: '警告・エラー',
    text: [
      '以下の Markdown 形式で、警告・エラーに分類されそうなイベントを回答してください。',
      '',
      '## 概要',
      '（警告・エラー候補の有無）',
      '',
      '## 一覧',
      '（該当しそうな event_type を列挙。種別・件数・時刻）',
      '',
      '## 時系列での変化',
      '（前半／後半の増減、集中時刻）',
      '',
      '## 所見',
      '',
      STRUCTURED_OUTPUT_FOOTER,
    ].join('\n'),
  },
  {
    id: 'default-sample-metrics-hint',
    label: 'メトリクス併用',
    text: [
      '以下の Markdown 形式で、期間メトリクス（CPU・メモリ等）とイベントを対照して回答してください。',
      '',
      '## 概要',
      '（メトリクスとイベントの対照可否）',
      '',
      '## メトリクス観測',
      '（period_metrics の傾向。高負荷と決めつけない）',
      '',
      '## イベントとの対照',
      '（event_time_buckets / occurred_at_* を同一時間軸で粗く対照）',
      '',
      '## ボトルネック兆候',
      '（読み取れる場合のみ。不明なら該当なし）',
      '',
      '## 所見',
      '（1 対 1 結合・因果断定はしない）',
      '',
      STRUCTURED_OUTPUT_FOOTER,
    ].join('\n'),
  },
]

/**
 * リセット・ストレージ初期化用に、`INITIAL_CHAT_SAMPLE_PROMPTS` のミュータブルなコピーを返す。
 */
export function getInitialChatSamplePromptsSnapshot(): ChatSamplePromptRow[] {
  return INITIAL_CHAT_SAMPLE_PROMPTS.map((r) => ({ id: r.id, label: r.label, text: r.text }))
}
