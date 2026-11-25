import { toErrorMessage } from '../../utils/errors'

export function errorText(error: unknown) {
  const text = toErrorMessage(error)
  try {
    const value = JSON.parse(text) as { detail?: unknown }
    return typeof value.detail === 'string' ? value.detail : '入力内容を確認してください。'
  } catch {
    return text
  }
}
