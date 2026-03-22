/**
 * 概要の要注意イベント一覧用「最小スコア」設定を Context と localStorage で共有する。
 */
import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { SummaryTopNotableMinScoreContext } from './summaryTopNotableMinScoreContext'
import {
  clampSummaryTopNotableMinScore,
  readStoredSummaryTopNotableMinScore,
  writeStoredSummaryTopNotableMinScore,
} from './summaryTopNotableMinScoreStorage'

/** マウント時に storage から初期値を読む。 */
function resolveInitialScore(): number {
  return readStoredSummaryTopNotableMinScore()
}

export function SummaryTopNotableMinScoreProvider({ children }: { children: ReactNode }) {
  const [topNotableMinScore, setTopNotableMinScoreState] = useState(resolveInitialScore)

  const setTopNotableMinScore = useCallback((n: number) => {
    const clamped = clampSummaryTopNotableMinScore(n)
    setTopNotableMinScoreState(clamped)
    writeStoredSummaryTopNotableMinScore(clamped)
  }, [])

  const value = useMemo(
    () => ({ topNotableMinScore, setTopNotableMinScore }),
    [topNotableMinScore, setTopNotableMinScore],
  )

  return (
    <SummaryTopNotableMinScoreContext.Provider value={value}>
      {children}
    </SummaryTopNotableMinScoreContext.Provider>
  )
}
