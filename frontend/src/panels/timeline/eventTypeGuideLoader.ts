import { apiGet } from '../../api'
import { eventTypeGuideListSchema, type EventTypeGuideSnippet } from '../../api/schemas'

/** イベント種別ガイドの引き当て。一覧を 1 回だけ取り、同時に何行開いても要求は 1 回にする。 */
export type GuideLoader = { get: (eventType: string) => Promise<EventTypeGuideSnippet | null> }

export function createGuideLoader(): GuideLoader {
  let pending: Promise<Map<string, EventTypeGuideSnippet>> | null = null
  const load = (): Promise<Map<string, EventTypeGuideSnippet>> => {
    if (!pending) {
      pending = apiGet<unknown>('/api/event-type-guides')
        .then((raw) => {
          const byType = new Map<string, EventTypeGuideSnippet>()
          for (const g of eventTypeGuideListSchema.parse(raw)) {
            byType.set(g.event_type, {
              general_meaning: g.general_meaning,
              typical_causes: g.typical_causes,
              remediation: g.remediation,
              action_required: g.action_required,
            })
          }
          return byType
        })
        .catch((e: unknown) => {
          pending = null // 失敗は覚えない（次に開いたとき取り直す）
          throw e
        })
    }
    return pending
  }
  return { get: async (eventType) => (await load()).get(eventType) ?? null }
}
