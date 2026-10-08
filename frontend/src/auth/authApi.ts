import {
  expectedPrincipalHeaders,
  notifyUnauthorized,
  principalMismatched,
  PRINCIPAL_SWITCHED_MESSAGE,
  SESSION_EXPIRED_MESSAGE,
} from '../api'
import { meSchema, realmsResponseSchema, type Me, type RealmsResponse } from '../api/schemas'
import { fetchWithActivity } from '../userActivity'

/**
 * 認証 API（``/api/auth``）の呼び出し。
 *
 * 共通の ``api.ts`` は 401 を「セッション切れ」として扱うため、ログイン前後の画面で使う
 * これらの呼び出しは独自に応答を解釈する。
 */

const GENERIC_ERROR = 'リクエストに失敗しました。時間をおいて再度お試しください。'
const RATE_LIMITED = 'ログインの試行回数が多すぎます。しばらく待ってから再度お試しください。'

const jsonHeaders: HeadersInit = { Accept: 'application/json' }
const mutationHeaders: HeadersInit = {
  ...jsonHeaders,
  'Content-Type': 'application/json',
  'X-Requested-With': 'XMLHttpRequest',
}

/** FastAPI の ``{"detail": "..."}`` から利用者向けの文言を取り出す（文字列のときだけ）。 */
async function detailOf(r: Response, fallback: string): Promise<string> {
  if (r.status >= 500) return GENERIC_ERROR
  if (r.status === 429) return RATE_LIMITED
  try {
    const body: unknown = await r.json()
    if (body && typeof body === 'object' && 'detail' in body) {
      const detail = (body as { detail: unknown }).detail
      if (typeof detail === 'string' && detail.trim() !== '') return detail
    }
  } catch {
    // JSON でない応答は既定の文言にする
  }
  return fallback
}

/** ログイン中の利用者。未ログインなら ``null``。 */
export async function fetchMe(): Promise<Me | null> {
  const r = await fetchWithActivity('/api/auth/me', { cache: 'no-store', headers: jsonHeaders as Record<string, string> })
  if (r.status === 401) return null
  if (!r.ok) throw new Error(await detailOf(r, GENERIC_ERROR))
  return meSchema.parse(await r.json())
}

export async function fetchRealms(): Promise<RealmsResponse> {
  const r = await fetch('/api/auth/realms', { cache: 'no-store', headers: jsonHeaders })
  if (!r.ok) throw new Error(await detailOf(r, GENERIC_ERROR))
  return realmsResponseSchema.parse(await r.json())
}

export async function login(params: {
  username: string
  password: string
  realm: string
}): Promise<Me> {
  const r = await fetch('/api/auth/login', {
    cache: 'no-store',
    method: 'POST',
    headers: mutationHeaders,
    body: JSON.stringify(params),
  })
  if (!r.ok) {
    throw new Error(await detailOf(r, 'ユーザー名またはパスワードが正しくありません。'))
  }
  return meSchema.parse(await r.json())
}

export async function logout(): Promise<void> {
  const r = await fetch('/api/auth/logout', {
    cache: 'no-store',
    method: 'POST',
    headers: mutationHeaders,
  })
  if (!r.ok) throw new Error(await detailOf(r, GENERIC_ERROR))
}

export async function changeOwnPassword(params: {
  current_password: string
  new_password: string
}): Promise<void> {
  const r = await fetch('/api/auth/me/password', {
    cache: 'no-store',
    method: 'POST',
    // 別のタブで別の利用者にログインし直されていたら、その利用者のパスワードを変えないようサーバが断る
    headers: { ...mutationHeaders, ...expectedPrincipalHeaders() },
    body: JSON.stringify(params),
  })
  if (principalMismatched(r)) throw new Error(PRINCIPAL_SWITCHED_MESSAGE)
  if (r.status === 401) {
    // セッションが切れているので、ほかの API と同じくログイン画面へ戻す
    notifyUnauthorized()
    throw new Error(SESSION_EXPIRED_MESSAGE)
  }
  if (!r.ok) throw new Error(await detailOf(r, GENERIC_ERROR))
}
