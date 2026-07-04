import { useContext } from 'react'
import { TimeZoneContext, type TimeZoneContextValue } from './timeZoneContext'

/** ``TimeZoneProvider`` 配下で表示 TZ と setter を取得する。 */
export function useTimeZone(): TimeZoneContextValue {
  const ctx = useContext(TimeZoneContext)
  if (!ctx) {
    throw new Error('useTimeZone must be used within TimeZoneProvider')
  }
  return ctx
}
