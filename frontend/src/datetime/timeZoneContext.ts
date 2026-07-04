import { createContext } from 'react'

export type TimeZoneContextValue = {
  timeZone: string
  setTimeZone: (tz: string) => void
}

/** 表示タイムゾーン Context。 */
export const TimeZoneContext = createContext<TimeZoneContextValue | null>(null)
