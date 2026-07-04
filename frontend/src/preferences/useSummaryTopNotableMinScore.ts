import { useContext } from 'react'
import {
  SummaryTopNotableMinScoreContext,
  type SummaryTopNotableMinScoreContextValue,
} from './summaryTopNotableMinScoreContext'

/** ``SummaryTopNotableMinScoreProvider`` 配下で最小スコア設定を取得する。 */
export function useSummaryTopNotableMinScore(): SummaryTopNotableMinScoreContextValue {
  const ctx = useContext(SummaryTopNotableMinScoreContext)
  if (!ctx) {
    throw new Error('useSummaryTopNotableMinScore must be used within SummaryTopNotableMinScoreProvider')
  }
  return ctx
}
