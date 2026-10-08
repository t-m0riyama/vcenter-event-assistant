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
export function onUnauthorized(listener: UnauthorizedListener): () => void {
  unauthorizedListeners.add(listener)
  return () => {
    unauthorizedListeners.delete(listener)
  }
}

function headers(): HeadersInit {
  return { Accept: 'application/json' }
}

/** 変更系 API 用ヘッダー（Cookie 認証の CSRF 対策。サーバの CsrfMiddleware が検査する）。 */
function mutationHeaders(): HeadersInit {
  return {
    ...headers(),
    'Content-Type': 'application/json',
    'X-Requested-With': 'XMLHttpRequest',
  }
}

/** ブラウザ既定キャッシュで GET が古い JSON を返すのを防ぐ */
const fetchNoStore: RequestInit = { cache: 'no-store' }

async function errorMessageFromResponse(r: Response): Promise<string> {
  const text = await r.text()
  if (r.status >= 500) {
    return GENERIC_API_ERROR
  }
  if (r.status === 401) {
    unauthorizedListeners.forEach((listener) => listener())
    return SESSION_EXPIRED_MESSAGE
  }
  if (r.status === 403) {
    return FORBIDDEN_MESSAGE
  }
  if (r.status === 422 || r.status === 409 || r.status === 413) {
    return text || GENERIC_API_ERROR
  }
  return GENERIC_API_ERROR
}

/** JSON GET（``cache: 'no-store'``）。 */
export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(path, { ...fetchNoStore, headers: headers() })
  if (!r.ok) throw new Error(await errorMessageFromResponse(r))
  return r.json() as Promise<T>
}

/** JSON POST。204 の場合は body なしとして ``undefined`` を返す。 */
export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
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
  const r = await fetch(path, {
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
  const r = await fetch(path, {
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
  const r = await fetch(path, {
    ...fetchNoStore,
    method: 'DELETE',
    headers: mutationHeaders(),
  })
  if (!r.ok) throw new Error(await errorMessageFromResponse(r))
}

/** JSON PUT. */
export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, { ...fetchNoStore, method: 'PUT', headers: mutationHeaders(), body: JSON.stringify(body) })
  if (!r.ok) throw new Error(await errorMessageFromResponse(r))
  return r.json() as Promise<T>
}
