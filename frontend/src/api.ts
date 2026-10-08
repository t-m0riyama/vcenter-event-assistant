import { fetchWithActivity } from './userActivity'

const GENERIC_API_ERROR =
  'リクエストに失敗しました。時間をおいて再度お試しください。'
export const SESSION_EXPIRED_MESSAGE = 'ログインの有効期限が切れました。再度ログインしてください。'
export const FORBIDDEN_MESSAGE = 'この操作を行う権限がありません。'

type UnauthorizedListener = () => void
const unauthorizedListeners = new Set<UnauthorizedListener>()

/**
 * API が 401（未ログイン・セッション切れ）を返したときに呼ばれる関数を登録する。
 * ログイン画面へ戻すために認証ゲートが使う。戻り値で登録を解除する。
 */
type PrincipalListener = (principalId: string) => void
const principalListeners = new Set<PrincipalListener>()

/**
 * 認証済みの応答が示す利用者とセッション（``X-VEA-Principal``）を受け取る関数を登録する。別のタブで
 * ログインし直すと（別のアカウントでも、ロール変更後の同じアカウントでも）、401 にならずに新しいセッションで
 * 成功し続けるため、認証ゲートが表示中の利用者と照合する。
 */
export function onPrincipalSeen(listener: PrincipalListener): () => void {
  principalListeners.add(listener)
  return () => {
    principalListeners.delete(listener)
  }
}

export const PRINCIPAL_SWITCHED_MESSAGE =
  '別のタブで利用者が切り替わりました。画面を新しい利用者に合わせて更新します。'

/** 画面に表示中の利用者とセッション（``/api/auth/me`` の ``principal_id``）。認証ゲートが設定する。 */
let expectedPrincipal: string | null = null

export function setExpectedPrincipal(principalId: string | null): void {
  expectedPrincipal = principalId
}

/**
 * 操作の報告を付けて送り、応答が示す利用者を通知する。表示中の利用者と違う利用者の応答は、要求した
 * 画面（前の利用者のもの）に渡さずにエラーにする。照合が済むまで別の利用者のデータを表示しないため。
 */
async function send(path: string, init: RequestInit): Promise<Response> {
  const r = await fetchWithActivity(path, {
    ...init,
    headers: { ...(init.headers as Record<string, string>), ...expectedPrincipalHeaders() },
  })
  if (principalMismatched(r)) throw new Error(PRINCIPAL_SWITCHED_MESSAGE)
  return r
}

/**
 * 表示中の利用者をサーバに伝えるヘッダ。サーバは Cookie の利用者と違えば要求を実行せずに 409 で断る
 * （応答を捨てるだけでは、変更系の要求が別の利用者として実行されてしまうため）。
 */
export function expectedPrincipalHeaders(): Record<string, string> {
  return expectedPrincipal ? { 'X-VEA-Expected-Principal': expectedPrincipal } : {}
}

/**
 * ``fetch`` を通らないブラウザ自身の要求（ファイルのダウンロードなど）の直前に呼び、送る URL を返す。
 * 先にセッションと表示中の利用者を確かめ（401 ならログイン画面へ、別の利用者なら照合して例外）、
 * URL にも表示中の利用者を付けてサーバに照合させる（確かめた後に切り替わっても別の利用者として実行しない）。
 * 値は利用者とセッションの行の ID で、Cookie のトークンのような資格情報ではない。
 */
export async function prepareBrowserRequest(url: string): Promise<string> {
  await apiGet<unknown>('/api/auth/me')
  if (!expectedPrincipal) return url
  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}vea_expected_principal=${encodeURIComponent(expectedPrincipal)}`
}

/** 応答が示す利用者を通知し、表示中の利用者と違えば true を返す。 */
export function principalMismatched(r: Response): boolean {
  const principalId = r.headers.get('X-VEA-Principal')
  if (!principalId) return false
  principalListeners.forEach((listener) => listener(principalId))
  return Boolean(expectedPrincipal && principalId !== expectedPrincipal)
}

export function notifyUnauthorized(): void {
  unauthorizedListeners.forEach((listener) => listener())
}

export function onUnauthorized(listener: UnauthorizedListener): () => void {
  unauthorizedListeners.add(listener)
  return () => {
    unauthorizedListeners.delete(listener)
  }
}

function headers(): Record<string, string> {
  return { Accept: 'application/json' }
}

/** 変更系 API 用ヘッダー（Cookie 認証の CSRF 対策。サーバの CsrfMiddleware が検査する）。 */
function mutationHeaders(): Record<string, string> {
  return {
    ...headers(),
    'Content-Type': 'application/json',
    'X-Requested-With': 'XMLHttpRequest',
  }
}

// 要求は fetchWithActivity で送る。利用者が操作していないときの要求（定期更新）は、
// サーバでセッションの無操作期限を延ばさない

/** ブラウザ既定キャッシュで GET が古い JSON を返すのを防ぐ */
const fetchNoStore: RequestInit = { cache: 'no-store' }

/** FastAPI の ``{"detail": "..."}`` なら detail の文字列を返す（それ以外は null）。 */
function detailMessage(text: string): string | null {
  try {
    const body: unknown = JSON.parse(text)
    if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
      return body.detail
    }
  } catch {
    // JSON でなければ本文をそのまま使う
  }
  return null
}

async function errorMessageFromResponse(r: Response): Promise<string> {
  const text = await r.text()
  if (r.status >= 500) {
    return GENERIC_API_ERROR
  }
  if (r.status === 401) {
    notifyUnauthorized()
    return SESSION_EXPIRED_MESSAGE
  }
  if (r.status === 403) {
    return FORBIDDEN_MESSAGE
  }
  if (r.status === 422 || r.status === 409 || r.status === 413) {
    return detailMessage(text) ?? (text || GENERIC_API_ERROR)
  }
  return GENERIC_API_ERROR
}

/** JSON GET（``cache: 'no-store'``）。 */
export async function apiGet<T>(path: string): Promise<T> {
  const r = await send(path, { ...fetchNoStore, headers: headers() })
  if (!r.ok) throw new Error(await errorMessageFromResponse(r))
  return r.json() as Promise<T>
}

/** JSON POST。204 の場合は body なしとして ``undefined`` を返す。 */
export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const r = await send(path, {
    ...fetchNoStore,
    method: 'POST',
    headers: mutationHeaders(),
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await errorMessageFromResponse(r))
  if (r.status === 204) return undefined as T
  return r.json() as Promise<T>
}

/**
 * multipart/form-data POST（ファイルアップロード用）。
 *
 * ``Content-Type`` はブラウザに boundary 付きで設定させるため、明示的に指定しない。
 */
export async function apiPostForm<T>(path: string, body: FormData): Promise<T> {
  const r = await send(path, {
    ...fetchNoStore,
    method: 'POST',
    headers: { ...headers(), 'X-Requested-With': 'XMLHttpRequest' },
    body,
  })
  if (!r.ok) throw new Error(await errorMessageFromResponse(r))
  if (r.status === 204) return undefined as T
  return r.json() as Promise<T>
}

/** JSON PATCH。 */
export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const r = await send(path, {
    ...fetchNoStore,
    method: 'PATCH',
    headers: mutationHeaders(),
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await errorMessageFromResponse(r))
  return r.json() as Promise<T>
}

/** JSON DELETE。 */
export async function apiDelete(path: string): Promise<void> {
  const r = await send(path, {
    ...fetchNoStore,
    method: 'DELETE',
    headers: mutationHeaders(),
  })
  if (!r.ok) throw new Error(await errorMessageFromResponse(r))
}

/** JSON PUT. */
export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const r = await send(path, { ...fetchNoStore, method: 'PUT', headers: mutationHeaders(), body: JSON.stringify(body) })
  if (!r.ok) throw new Error(await errorMessageFromResponse(r))
  return r.json() as Promise<T>
}
