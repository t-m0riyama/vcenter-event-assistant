import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { getSortedTimeZoneOptions } from './listTimeZones'
import {
  getDefaultBrowserTimeZone,
  isValidIanaTimeZone,
  readStoredTimeZone,
  writeStoredTimeZone,
} from './timeZoneStorage'

function resolveInitialTimeZone(): string {
  const stored = readStoredTimeZone()
  if (stored && isValidIanaTimeZone(stored)) {
    return stored
  }
  const tz = getDefaultBrowserTimeZone()
  writeStoredTimeZone(tz)
  return tz
}

type TimeZoneContextValue = {
  timeZone: string
  setTimeZone: (tz: string) => void
}

const TimeZoneContext = createContext<TimeZoneContextValue | null>(null)

export function TimeZoneProvider({ children }: { children: ReactNode }) {
  const [timeZone, setTimeZoneState] = useState(resolveInitialTimeZone)

  const setTimeZone = useCallback((tz: string) => {
    if (!isValidIanaTimeZone(tz)) {
      return
    }
    setTimeZoneState(tz)
    writeStoredTimeZone(tz)
  }, [])

  const value = useMemo(
    () => ({ timeZone, setTimeZone }),
    [timeZone, setTimeZone],
  )

  return (
    <TimeZoneContext.Provider value={value}>{children}</TimeZoneContext.Provider>
  )
}

export function useTimeZone(): TimeZoneContextValue {
  const ctx = useContext(TimeZoneContext)
  if (!ctx) {
    throw new Error('useTimeZone must be used within TimeZoneProvider')
  }
  return ctx
}

export function TimeZoneSelect() {
  const { timeZone, setTimeZone } = useTimeZone()
  const baseOptions = useMemo(() => getSortedTimeZoneOptions(), [])
  const options = useMemo(() => {
    if (baseOptions.includes(timeZone)) {
      return baseOptions
    }
    return [...baseOptions, timeZone].sort((a, b) => a.localeCompare(b))
  }, [baseOptions, timeZone])

  return (
    <label className="tz-select">
      表示タイムゾーン
      <select
        value={timeZone}
        onChange={(e) => setTimeZone(e.target.value)}
      >
        {options.map((z) => (
          <option key={z} value={z}>
            {z}
          </option>
        ))}
      </select>
    </label>
  )
}
