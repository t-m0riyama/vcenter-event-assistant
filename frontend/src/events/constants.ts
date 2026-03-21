export const EVENT_PAGE_SIZES = [20, 50, 100, 200] as const

/** Matches `GET /api/events` max `limit` for chunked export. */
export const EVENT_EXPORT_CHUNK = 200

export const EVENT_TEXT_FILTER_SUMMARY_CLIP = 18
export const EVENT_TEXT_FILTER_SUMMARY_MAX = 96
