import { useCallback, useEffect, useState } from 'react'
import { apiGet } from '../api'
import { appConfigSchema, type AppConfig } from '../api/schemas'
import { toErrorMessage } from '../utils/errors'

/**
 * Loads `/api/config` once on mount and exposes retention settings for the shell.
 */
export function useAppConfig(reportError: (message: string | null) => void) {
  const [retention, setRetention] = useState<AppConfig | null>(null)

  const loadConfig = useCallback(async () => {
    try {
      const raw = await apiGet<unknown>('/api/config')
      setRetention(appConfigSchema.parse(raw))
    } catch (e) {
      setRetention(null)
      reportError(toErrorMessage(e))
    }
  }, [reportError])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- mount fetch
    void loadConfig()
  }, [loadConfig])

  return { retention, reloadConfig: loadConfig }
}
