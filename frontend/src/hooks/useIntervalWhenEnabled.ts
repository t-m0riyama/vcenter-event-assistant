import { useEffect } from 'react'

/**
 * `enabled` が真のときだけ `intervalMs` 間隔で `callback` を実行する。
 * アンマウント時および `enabled` / 間隔 / コールバック変更時に `clearInterval` する。
 *
 * @param enabled タイマーを張るかどうか
 * @param intervalMs 間隔（ミリ秒）。0 以下または非有限のときはタイマーを張らない
 * @param callback 各ティックで呼ぶ処理（同期関数）
 */
export function useIntervalWhenEnabled(
  enabled: boolean,
  intervalMs: number,
  callback: () => void,
): void {
  useEffect(() => {
    if (!enabled || !Number.isFinite(intervalMs) || intervalMs <= 0) {
      return
    }
    const id = window.setInterval(() => {
      callback()
    }, intervalMs)
    return () => {
      clearInterval(id)
    }
  }, [enabled, intervalMs, callback])
}
