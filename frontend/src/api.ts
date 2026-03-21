function headers(): HeadersInit {
  return { Accept: 'application/json' }
}

export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: headers() })
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json() as Promise<T>
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: 'POST',
    headers: { ...headers(), 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  if (r.status === 204) return undefined as T
  return r.json() as Promise<T>
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: 'PATCH',
    headers: { ...headers(), 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json() as Promise<T>
}

export async function apiDelete(path: string): Promise<void> {
  const r = await fetch(path, { method: 'DELETE', headers: headers() })
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
}
