/**
 * 最新アシスタント行の先頭を会話リストの表示上端付近に置くときの余白（px）。
 */
export const CHAT_ASSISTANT_MESSAGE_LIST_TOP_MARGIN_PX = 8

export type ComputeScrollTopToShowChildAtListTopInput = {
  readonly childOffsetTop: number
  readonly scrollHeight: number
  readonly clientHeight: number
  readonly marginPx: number
}

/**
 * 縦スクロールリスト内で、子要素の上端がビューポート上端付近に来るよう `scrollTop` を算出する。
 */
export function computeScrollTopToShowChildAtListTop(
  input: ComputeScrollTopToShowChildAtListTopInput,
): number {
  const maxScroll = Math.max(0, input.scrollHeight - input.clientHeight)
  const desired = input.childOffsetTop - input.marginPx
  return Math.min(Math.max(desired, 0), maxScroll)
}
