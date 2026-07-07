/**
 * `crypto.randomUUID` は secure context（HTTPS または localhost）でのみ利用可能なため、
 * 非 secure context（例: 社内 LAN での HTTP アクセス）ではこの関数自体が存在せず、
 * 呼び出し側で `TypeError: crypto.randomUUID is not a function` が発生する。
 * 本関数は利用可能ならそれを使い、不可なら `crypto.getRandomValues` ベースの
 * フォールバック（それも不可なら Math.random ベース）で ID を生成する。
 */
export function randomId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    const bytes = crypto.getRandomValues(new Uint8Array(16))
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
  }
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`
}
