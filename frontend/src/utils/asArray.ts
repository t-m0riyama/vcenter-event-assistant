/**
 * Coerces unknown API fields to arrays so `.map` never runs on null / objects (runtime safety).
 */
export function asArray<T>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : []
}
