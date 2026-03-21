import { useContext } from 'react'
import { TimeZoneContext, type TimeZoneContextValue } from './timeZoneContext'

export function useTimeZone(): TimeZoneContextValue {
  const ctx = useContext(TimeZoneContext)
  if (!ctx) {
    throw new Error('useTimeZone must be used within TimeZoneProvider')
  }
  return ctx
}
