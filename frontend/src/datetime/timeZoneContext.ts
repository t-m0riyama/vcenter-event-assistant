import { createContext } from 'react'

export type TimeZoneContextValue = {
  timeZone: string
  setTimeZone: (tz: string) => void
}

export const TimeZoneContext = createContext<TimeZoneContextValue | null>(null)
