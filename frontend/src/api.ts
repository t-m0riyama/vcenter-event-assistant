import { fetchWithActivity } from './userActivity'

export const GENERIC_API_ERROR =
  'リクエストに失敗しました。時間をおいて再度お試しください。'
export const SESSION_EXPIRED_MESSAGE = 'ログインの有効期限が切れました。再度ログインしてください。'
export const FORBIDDEN_MESSAGE = 'この操作を行う権限がありません。'

/** ``notice`` はログイン画面に出す理由（省略するとセッション切れの文言）。 */
type UnauthorizedListener = (notice?: string) => void
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
async function send(path: string, init: RequestInit, principalId?: string): Promise<Response> {
  const r = await fetchWithActivity(path, {
    ...init,
    headers: {
      ...(init.headers as Record<string, string>),
      ...(principalId === undefined ? expectedPrincipalHeaders() : { 'X-VEA-Expected-Principal': principalId }),
    },
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

/**
 * セッションが無効になった可能性を認証ゲートに伝える。``notice`` はログイン画面に出す理由
 * （自分のセッションも失効させる操作の後など。省略するとセッション切れの文言）。
 */
export function notifyUnauthorized(notice?: string): void {
  unauthorizedListeners.forEach((listener) => listener(notice))
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

function responseDetail(text: string): unknown {
  try {
    const body: unknown = JSON.parse(text)
    if (body && typeof body === 'object' && 'detail' in body) {
      return body.detail
    }
  } catch {
    // JSON でなければ本文をそのまま使う
  }
  return null
}

/** Pydantic の検証エラーを「項目: 理由」の形に整える。 */
export function formatValidationMessage(text: string): string | null {
  return formatValidationDetail(responseDetail(text))
}

function formatValidationDetail(detail: unknown): string | null {
  if (!Array.isArray(detail)) return null
  const lines = detail.flatMap((entry: unknown) => {
    if (!entry || typeof entry !== 'object' || !('msg' in entry) || typeof entry.msg !== 'string') return []
    const loc = 'loc' in entry && Array.isArray(entry.loc)
      ? entry.loc.filter((part: unknown) => part !== 'body').join('.')
      : ''
    return [loc ? `${loc}: ${entry.msg}` : entry.msg]
  })
  return lines.length > 0 ? lines.join(' / ') : null
}

function responseErrorMessage(status: number, text: string, detail: unknown, download: boolean): string {
  if (status >= 500) {
    return GENERIC_API_ERROR
  }
  if (status === 401) {
    notifyUnauthorized()
    return SESSION_EXPIRED_MESSAGE
  }
  if (status === 403) {
    return FORBIDDEN_MESSAGE
  }
  if ([422, 409, 413].includes(status) || (download && status === 400)) {
    if (download && status === 422) {
      const message = typeof detail === 'string' ? detail : formatValidationDetail(detail)
      return message?.trim() ? message : GENERIC_API_ERROR
    }
    if (typeof detail === 'string') return detail
    if (download) return GENERIC_API_ERROR
    return text || GENERIC_API_ERROR
  }
  return GENERIC_API_ERROR
}

/** API の失敗。``message`` は利用者向けの文言。 */
export class ApiError extends Error {
  /** HTTP の状態コード。 */
  readonly status: number
  /** サーバが理由を見分けられるよう付けた ``X-VEA-Error-Code``（なければ null）。 */
  readonly errorCode: string | null
  /** ``Retry-After``（秒）。ヘッダが無い・秒数として読めないときは null。 */
  readonly retryAfterSeconds: number | null
  /** サーバーの JSON 応答に含まれる detail。 */
  readonly detail: unknown

  constructor(
    message: string,
    status: number,
    errorCode: string | null,
    retryAfterSeconds: number | null = null,
    detail: unknown = null,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.errorCode = errorCode
    this.retryAfterSeconds = retryAfterSeconds
    this.detail = detail
  }
}

async function apiError(r: Response, { download = false } = {}): Promise<ApiError> {
  const retryAfter = Number(r.headers.get('Retry-After'))
  const body = await r.text()
  const detail = responseDetail(body)
  return new ApiError(
    responseErrorMessage(r.status, body, detail, download),
    r.status,
    r.headers.get('X-VEA-Error-Code'),
    Number.isFinite(retryAfter) && retryAfter >= 0 && r.headers.get('Retry-After') !== null ? retryAfter : null,
    detail,
  )
}

/** Retry-After が無ければ 3 秒、値が大きくても最大 10 秒待つ。 */
export async function waitForRetryAfter(seconds: number | null, signal?: AbortSignal): Promise<void> {
  signal?.throwIfAborted()
  await new Promise<void>((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer)
      reject(signal?.reason)
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, Math.min((seconds ?? 3) * 1000, 10_000))
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

type BlobRequest = { signal?: AbortSignal } & (
  | { method?: 'GET' }
  | { method: 'POST'; body: unknown }
)

function attachmentFilename(disposition: string): string | null {
  let filename = null
  const parameters = disposition.matchAll(/;\s*([^=;\s]+)\s*=\s*(?:"((?:\\.|[^"\\])*)"|([^";\s]+))/g)
  for (const [, name, quoted, token] of parameters) {
    if (name.toLowerCase() === 'filename') {
      filename = quoted?.replace(/\\(.)/g, '$1') ?? token
    } else if (name.toLowerCase() === 'filename*' && token) {
      const encoded = /^UTF-8'[^']*'(.+)$/i.exec(token)?.[1]
      if (!encoded) continue
      try {
        return decodeURIComponent(encoded)
      } catch {
        // 拡張形式を読めない場合は通常のファイル名を使う。
      }
    }
  }
  return filename || null
}

/** ファイルと添付名を受け取る。503 のときだけ待って 1 回再試行する。 */
export async function apiFetchBlob(
  path: string,
  options: BlobRequest = {},
): Promise<{ blob: Blob; filename: string | null }> {
  const { method = 'GET', signal } = options
  const principal = expectedPrincipal
  const init: RequestInit = {
    ...fetchNoStore,
    method,
    signal,
    headers: {
      ...(options.method === 'POST' ? mutationHeaders() : {}),
      Accept: '*/*',
    },
    ...(options.method === 'POST' ? { body: JSON.stringify(options.body) } : {}),
  }
  const call = async () => {
    signal?.throwIfAborted()
    if (expectedPrincipal !== principal) throw new Error(PRINCIPAL_SWITCHED_MESSAGE)
    const r = await send(path, init)
    if (!r.ok) throw await apiError(r, { download: true })
    const disposition = r.headers.get('Content-Disposition') ?? ''
    return { blob: await r.blob(), filename: attachmentFilename(disposition) }
  }
  try {
    return await call()
  } catch (e) {
    if (!(e instanceof ApiError) || e.status !== 503) throw e
    await waitForRetryAfter(e.retryAfterSeconds, signal)
    return call()
  }
}

/** JSON GET（``cache: 'no-store'``）。 */
export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const r = await send(path, { ...fetchNoStore, headers: headers(), ...(signal && { signal }) })
  if (!r.ok) throw await apiError(r)
  return r.json() as Promise<T>
}

/** JSON POST。204 の場合は body なしとして ``undefined`` を返す。 */
export async function apiPost<T>(path: string, body: unknown, principalId?: string): Promise<T> {
  const r = await send(path, {
    ...fetchNoStore,
    method: 'POST',
    headers: mutationHeaders(),
    body: JSON.stringify(body),
  }, principalId)
  if (!r.ok) throw await apiError(r)
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
  if (!r.ok) throw await apiError(r)
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
  if (!r.ok) throw await apiError(r)
  return r.json() as Promise<T>
}

/** JSON DELETE。 */
export async function apiDelete(path: string): Promise<void> {
  const r = await send(path, {
    ...fetchNoStore,
    method: 'DELETE',
    headers: mutationHeaders(),
  })
  if (!r.ok) throw await apiError(r)
}

/** JSON PUT. */
export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const r = await send(path, { ...fetchNoStore, method: 'PUT', headers: mutationHeaders(), body: JSON.stringify(body) })
  if (!r.ok) throw await apiError(r)
  return r.json() as Promise<T>
}
