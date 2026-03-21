/**
 * Normalizes thrown values or API errors to a user-facing string.
 */
export function toErrorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}
