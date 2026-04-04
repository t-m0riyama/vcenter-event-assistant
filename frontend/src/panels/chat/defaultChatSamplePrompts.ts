import type { ChatSamplePromptRow } from './chatSamplePromptTypes'

/** チャットパネルに出す既定サンプル（コード同梱・読み取り専用）。 */
export const DEFAULT_CHAT_SAMPLE_PROMPTS: readonly ChatSamplePromptRow[] = [
  {
    id: 'default-sample-period-summary',
    label: '期間の要約',
    text: 'この期間のイベントと傾向を、重要度が高い順に要約してください。',
  },
  {
    id: 'default-sample-power-events',
    label: '電源・可用性',
    text:
      'この期間に集約されたイベントのうち、電源操作や可用性に関連しそうなものの傾向を説明してください。',
  },
  {
    id: 'default-sample-alerts',
    label: '警告・エラー',
    text: '警告やエラーに分類されそうなイベントがあれば列挙し、時系列での変化も述べてください。',
  },
  {
    id: 'default-sample-metrics-hint',
    label: 'メトリクス併用',
    text:
      '期間メトリクス（CPU・メモリ等）をコンテキストに含めたうえで、負荷やボトルネックの兆候が読み取れるか整理してください。',
  },
]
