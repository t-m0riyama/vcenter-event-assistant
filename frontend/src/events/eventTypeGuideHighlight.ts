import type { EventTypeGuideSnippet } from '../api/schemas'

/**
 * 種別ガイドで「対処が必要」とマークされた行を一覧で強調するかどうか。
 */
export function shouldHighlightEventRowForAction(
  typeGuide: EventTypeGuideSnippet | null | undefined,
): boolean {
  return typeGuide?.action_required === true
}
