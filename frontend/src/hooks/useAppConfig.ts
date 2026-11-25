import { useCallback, useEffect, useState } from 'react'
import { apiGet } from '../api'
import { appConfigSchema, type AppConfig } from '../api/schemas'
import { toErrorMessage } from '../utils/errors'

/**
 * Loads `/api/config` once on mount and exposes retention settings for the shell.
 */
export function useAppConfig(reportError: (message: string | null) => void) {
  const [retention, setRetention] = useState<AppConfig | null>(null)

  const [configLoading, setConfigLoading] = useState(true)

  const loadConfig = useCallback(async () => {
    try {
      const raw = await apiGet<unknown>('/api/config')
      setRetention(appConfigSchema.parse(raw))
    } catch (e) {
      setRetention(null)
      reportError(toErrorMessage(e))
    } finally {
      setConfigLoading(false)
    }
  }, [reportError])

  useEffect(() => {
    void loadConfig()
  }, [loadConfig])

  return { retention, configLoading, reloadConfig: loadConfig }
}
