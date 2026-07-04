import { useCallback, useState } from 'react'

import {
  DEFAULT_METRIC_THRESHOLD_CPU_PCT,
  DEFAULT_METRIC_THRESHOLD_DISK_PCT,
  DEFAULT_METRIC_THRESHOLD_MEMORY_PCT,
  DEFAULT_METRIC_THRESHOLD_NETWORK_PCT,
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
  metricThresholdDiskPct: number
  metricThresholdDiskInput: string
  setMetricThresholdDiskPct: (value: number) => void
  setMetricThresholdDiskInput: (value: string) => void
  metricThresholdNetworkPct: number
  metricThresholdNetworkInput: string
  setMetricThresholdNetworkPct: (value: number) => void
  setMetricThresholdNetworkInput: (value: string) => void
  handleMetricThresholdInputChange: (
    rawValue: string,
    setInput: (value: string) => void,
    setValue: (value: number) => void,
  ) => void
}

/**
 * Chat / Timeline で共有するメトリクス閾値（数値 + 入力文字列）の状態。
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
  const [metricThresholdDiskPct, setMetricThresholdDiskPct] = useState(DEFAULT_METRIC_THRESHOLD_DISK_PCT)
  const [metricThresholdDiskInput, setMetricThresholdDiskInput] = useState(
    String(DEFAULT_METRIC_THRESHOLD_DISK_PCT),
  )
  const [metricThresholdNetworkPct, setMetricThresholdNetworkPct] = useState(
    DEFAULT_METRIC_THRESHOLD_NETWORK_PCT,
  )
  const [metricThresholdNetworkInput, setMetricThresholdNetworkInput] = useState(
    String(DEFAULT_METRIC_THRESHOLD_NETWORK_PCT),
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
    metricThresholdDiskPct,
    metricThresholdDiskInput,
    setMetricThresholdDiskPct,
    setMetricThresholdDiskInput,
    metricThresholdNetworkPct,
    metricThresholdNetworkInput,
    setMetricThresholdNetworkPct,
    setMetricThresholdNetworkInput,
    handleMetricThresholdInputChange,
  }
}
