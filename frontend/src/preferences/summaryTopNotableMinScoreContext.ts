import { createContext } from 'react'

export type SummaryTopNotableMinScoreContextValue = {
  topNotableMinScore: number
  setTopNotableMinScore: (n: number) => void
}

export const SummaryTopNotableMinScoreContext =
  createContext<SummaryTopNotableMinScoreContextValue | null>(null)
