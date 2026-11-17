import { useCallback, useState } from 'react'

import {
  DEFAULT_METRIC_THRESHOLD_CPU_PCT,
  DEFAULT_METRIC_THRESHOLD_MEMORY_PCT,
  isValidMetricThresholdPercent,
} from './periodMetricThresholdDefaults'

export type PeriodMetricThresholdFields = {
  metricThresholdCpuPct: number
  metricThresholdCpuInput: string
  setMetricThresholdCpuPct: (value: number) => void
  setMetricThresholdCpuInput: (value: string) => void
  metricThresholdMemoryPct: number
  metricThresholdMemoryInput: string
  setMetricThresholdMemoryPct: (value: number) => void
  setMetricThresholdMemoryInput: (value: string) => void
  handleMetricThresholdInputChange: (
    rawValue: string,
    setInput: (value: string) => void,
    setValue: (value: number) => void,
  ) => void
}

/**
 * チャットのメトリクス閾値（数値 + 入力文字列）の状態。対象は単位が % の CPU とメモリだけ。
 */
export function usePeriodMetricThresholdFields(): PeriodMetricThresholdFields {
  const [metricThresholdCpuPct, setMetricThresholdCpuPct] = useState(DEFAULT_METRIC_THRESHOLD_CPU_PCT)
  const [metricThresholdCpuInput, setMetricThresholdCpuInput] = useState(
    String(DEFAULT_METRIC_THRESHOLD_CPU_PCT),
  )
  const [metricThresholdMemoryPct, setMetricThresholdMemoryPct] = useState(
    DEFAULT_METRIC_THRESHOLD_MEMORY_PCT,
  )
  const [metricThresholdMemoryInput, setMetricThresholdMemoryInput] = useState(
    String(DEFAULT_METRIC_THRESHOLD_MEMORY_PCT),
  )

  const handleMetricThresholdInputChange = useCallback(
    (
      rawValue: string,
      setInput: (value: string) => void,
      setValue: (value: number) => void,
    ) => {
      setInput(rawValue)
      if (rawValue.trim() === '') {
        return
      }
      const parsed = Number(rawValue)
      if (!isValidMetricThresholdPercent(parsed)) {
        return
      }
      setValue(parsed)
    },
    [],
  )

  return {
    metricThresholdCpuPct,
    metricThresholdCpuInput,
    setMetricThresholdCpuPct,
    setMetricThresholdCpuInput,
    metricThresholdMemoryPct,
    metricThresholdMemoryInput,
    setMetricThresholdMemoryPct,
    setMetricThresholdMemoryInput,
    handleMetricThresholdInputChange,
  }
}
