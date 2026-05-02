import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useMetricDataFetch } from './useMetricDataFetch'
import * as api from '../api'

vi.mock('../api', () => ({
  apiGet: vi.fn(() => Promise.resolve([])),
}))

describe('useMetricDataFetch', () => {
  it('初期状態が正しいこと', () => {
    const { result } = renderHook(() => useMetricDataFetch({
      vcenterId: '',
      metricKey: '',
      rangeFromInput: '2026-01-01T00:00',
      rangeToInput: '2026-01-02T00:00',
      timeZone: 'UTC',
      perfBucketSeconds: 300,
      chartEventType: '',
      onError: vi.fn(),
    }))
    
    expect(result.current.loading).toBe(false)
    expect(result.current.vcenters).toEqual([])
  })
})
