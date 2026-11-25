import { useRef, useState } from 'react'
import type { TimelineExportActivity } from './TimelineExportControls'

/** 同じ画面の出力ボタンから同時にダウンロードを始めないようにする。 */
export function useTimelineExportActivity(): TimelineExportActivity {
  const [active, setActive] = useState<TimelineExportActivity['active']>(null)
  const inProgress = useRef(false)
  return {
    active,
    claim(ownerId, format) {
      if (inProgress.current) return false
      inProgress.current = true
      setActive({ ownerId, format })
      return true
    },
    release() {
      inProgress.current = false
      setActive(null)
    },
  }
}
