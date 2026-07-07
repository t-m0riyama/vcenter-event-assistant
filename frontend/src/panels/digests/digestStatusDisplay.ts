import type { DigestRead } from '../../api/schemas'

/** API が返す保存済み status（後方互換で ``ok`` + ``error_message`` も LLM 失敗扱い）。 */
export type DigestEffectiveStatus = 'ok' | 'ok_llm_failed' | 'error' | string

/**
 * 一覧・詳細バッジ用の実効 status。
 * 旧データ（``status=ok`` かつ ``error_message`` あり）は ``ok_llm_failed`` とみなす。
 */
export function resolveDigestEffectiveStatus(
  digest: Pick<DigestRead, 'status' | 'error_message'>,
): DigestEffectiveStatus {
  if (
    digest.status === 'ok' &&
    digest.error_message != null &&
    digest.error_message.trim() !== ''
  ) {
    return 'ok_llm_failed'
  }
  return digest.status
}

/** バッジ表示用の短い日本語ラベル。 */
export function digestStatusLabel(status: DigestEffectiveStatus): string {
  switch (status) {
    case 'ok':
      return '正常'
    case 'ok_llm_failed':
      return 'LLM 失敗'
    case 'error':
      return 'エラー'
    default:
      return status
  }
}
