import { useCallback, useEffect, useState } from 'react'
import { apiGet } from '../api'
import { dashboardAttentionSchema, type DashboardAttention } from '../api/schemas'

/** ドットの更新間隔。attention API はカウント 2 つだけの軽量エンドポイント */
const ATTENTION_POLL_INTERVAL_MS = 60_000

/**
 * タブのアテンションドット用に軽量サマリを取得する。
 * マウント時に 1 回取得し、以後は固定間隔でポーリングする
 * （App は AppProviders の外側のため自動更新設定のコンテキストは使えない。
 * 異常の見落とし防止が目的なので、自動更新 OFF でも動く固定間隔とする）。
 * 補助情報のため取得失敗は無視する（エラーバナーは出さない）。
 */
export function useAttentionStatus(): DashboardAttention | null {
  const [attention, setAttention] = useState<DashboardAttention | null>(null)

  const load = useCallback(async () => {
    try {
      const raw = await apiGet<unknown>('/api/dashboard/attention')
      setAttention(dashboardAttentionSchema.parse(raw))
    } catch {
      // 補助表示のため無視（次回のポーリングで回復する）
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- mount fetch
    void load()
    const id = window.setInterval(() => {
      void load()
    }, ATTENTION_POLL_INTERVAL_MS)
    return () => window.clearInterval(id)
  }, [load])

  return attention
}
