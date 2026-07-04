export type ImportApiErrorFormatOptions = {
  /** FastAPI `detail` 文字列の既知キーを日本語に置換する。 */
  apiDetailJa?: Readonly<Record<string, string>>
  /** HTTP 422 時のユーザー向けメッセージ。未指定時は汎用文言。 */
  format422Message?: (detailText: string | null) => string
}

const DEFAULT_422_MESSAGE =
  'サーバーが送信内容を検証できませんでした。送信データの形式と値を確認してください。'

/**
 * `apiPost` が投げる `Error`（先頭に HTTP ステータスと JSON 本文）を画面向けに整形する。
 */
export function formatImportApiError(err: unknown, options: ImportApiErrorFormatOptions = {}): string {
  if (!(err instanceof Error)) {
    return String(err)
  }

  const raw = err.message
  if (/failed to fetch/i.test(raw) || raw.includes('NetworkError')) {
    return 'ネットワークに接続できませんでした。接続を確認してから再度お試しください。'
  }

  const parsed = tryParseFastApiErrorBody(raw)
  if (!parsed) {
    return `インポートに失敗しました。${raw.length > 200 ? `${raw.slice(0, 200)}…` : raw}`
  }

  const { status, detailText } = parsed
  const { apiDetailJa, format422Message } = options

  if (detailText && apiDetailJa?.[detailText]) {
    return apiDetailJa[detailText]
  }

  if (status === 422) {
    return format422Message ? format422Message(detailText) : DEFAULT_422_MESSAGE
  }

  if (status === 400 && detailText) {
    return `リクエストを受け付けられませんでした。${detailText}`
  }

  if (status >= 500) {
    return 'サーバー側でエラーが発生しました。しばらくしてから再度お試しください。'
  }

  return `インポートに失敗しました（${status}）。${detailText ?? ''}`.trim()
}

function tryParseFastApiErrorBody(message: string): {
  status: number
  detailText: string | null
} | null {
  const head = message.match(/^(\d{3})\s+/)
  if (!head) return null
  const status = Number(head[1])
  const jsonStart = message.indexOf('{')
  if (jsonStart === -1) {
    return { status, detailText: message.slice(head[0].length).trim() || null }
  }

  try {
    const body = JSON.parse(message.slice(jsonStart)) as { detail?: unknown }
    return { status, detailText: flattenFastApiDetail(body.detail) }
  } catch {
    return { status, detailText: message.slice(head[0].length).trim() || null }
  }
}

function flattenFastApiDetail(detail: unknown): string | null {
  if (detail == null) return null
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (item && typeof item === 'object' && 'msg' in item) {
        const loc =
          'loc' in item && Array.isArray((item as { loc?: unknown }).loc)
            ? String((item as { loc: unknown[] }).loc.join('.'))
            : ''
        const msg = String((item as { msg: unknown }).msg)
        return loc ? `${loc}: ${msg}` : msg
      }
      return JSON.stringify(item)
    })
    return parts.join(' / ')
  }
  return JSON.stringify(detail)
}
