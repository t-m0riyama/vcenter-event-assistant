import { useContext } from 'react'
import {
  SummaryTopNotableMinScoreContext,
  type SummaryTopNotableMinScoreContextValue,
} from './summaryTopNotableMinScoreContext'

export function useSummaryTopNotableMinScore(): SummaryTopNotableMinScoreContextValue {
  const ctx = useContext(SummaryTopNotableMinScoreContext)
  if (!ctx) {
    throw new Error('useSummaryTopNotableMinScore must be used within SummaryTopNotableMinScoreProvider')
  }
  return ctx
}
