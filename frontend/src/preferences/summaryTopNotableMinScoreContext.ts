import { createContext } from 'react'

/** 概要の要注意イベント「最小スコア」設定の Context 値。 */
export type SummaryTopNotableMinScoreContextValue = {
  topNotableMinScore: number
  setTopNotableMinScore: (n: number) => void
}

export const SummaryTopNotableMinScoreContext =
  createContext<SummaryTopNotableMinScoreContextValue | null>(null)
