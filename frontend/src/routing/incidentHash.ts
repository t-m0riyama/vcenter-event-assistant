export const INCIDENTS_HASH = '#/incidents'

export function incidentIdFromHash(hash: string): string | null {
  const match = /^#\/incidents\/([^/?#]+)\/?(?:\?.*)?$/.exec(hash)
  if (!match) return null
  try {
    return decodeURIComponent(match[1])
  } catch {
    return match[1]
  }
}

export function incidentHash(id: string | null): string {
  return id === null ? INCIDENTS_HASH : `${INCIDENTS_HASH}/${encodeURIComponent(id)}`
}

export function replaceIncidentHash(id: string | null): void {
  const next = incidentHash(id)
  if (window.location.hash === next) return
  window.history.replaceState(null, '', next)
}
